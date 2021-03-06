import math
from abc import abstractmethod

import cv2
import pymunk

from Box2D import *

import sim_pymunk, sim_box2d
from .interface import PuckPredictor
from .calc import MovingAverage

def calculate_speed_angle(pos1, pos2, time1, time2):
    """
    :param pos1: x,y tuple position from time1
    :param pos2: x,y tuple position from time2
    :param time1: time stamp of pos1, units seconds
    :param time2: time stamp of pos2, units seconds
    """
    dy = pos2[1] - pos1[1]
    dx = pos2[0] - pos1[0]
    dt = (time2 - time1) / cv2.getTickFrequency()

    angle = math.atan2(dy, dx)
    speed = math.sqrt(dx * dx + dy * dy) / dt if dt != 0 else 0

    return speed, angle

class Circle(object):

    def __init__(self, x, y, radius):
        self.x = x
        self.y = y
        self.radius = radius

    def intersect(self, p1, p2):
        # Source: Watt, 3D Computer Graphics, Third Edition, p18-19
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]

        a = dx*dx + dy*dy
        b = 2*dx*(p1[0] - self.x) + 2*dy*(p1[1] - self.y)
        c = self.x*self.x + self.y*self.y + p1[0]*p1[0] + p1[1]*p1[1] + 2*(-self.x*p1[0] - self.y*p1[1]) - self.radius*self.radius

        disc = b*b - 4*a*c  # discriminant

        if disc > 0:
            disc_sqrt = math.sqrt(disc)  # fixme: better varname?
            t1 = (-b + disc_sqrt) / (2*a)
            t2 = (-b - disc_sqrt) / (2*a)

            # Minimum value is the closest, 
            # only values of t between 0 and 1 lie
            # on the circle
            t = min(t1, t2)
            if t >= 0 and t <= 1:
                x = p1[0] + t*dx
                y = p1[1] + t*dy

                return x,y

        return None

    def draw(self, frame, color=(255, 0, 0)):
        pos = (int(self.x), int(self.y))
        cv2.circle(frame, pos, int(self.radius), color, 2)

class TableSimPredictor(PuckPredictor):

    def __init__(self, width, height, avg_size=10, defense_radius=40):
        """
        :param width: table width in pixels
        :param height: table width in pixels
        :param avg_size: number of elements in moving average
        :param defense_radius: constraint circle for paddle movements in pixels
        """

        # Store current posistion and time 
        self.curr_pos = (0, 0)
        self.curr_time = 0

        # Cache predicted path for draw
        self.pred_path = []

        # Calculate angles and speeds as we get them so we
        # can keep a rolling sum 
        self.angles = MovingAverage(avg_size)
        self.speeds = MovingAverage(avg_size) 

        # Create defense circle located at center of right most goal
        self.defense_circle = Circle(width, height / 2, defense_radius)

    def add_puck_event(self, tick, coords, radius):

        last_pos = self.curr_pos
        last_time = self.curr_time

        self.curr_pos = coords
        self.curr_time = tick

        if tick == 0:
            speed, angle = (0, 0)
        else:
            speed, angle = calculate_speed_angle(last_pos, self.curr_pos, last_time, self.curr_time)

        self.speeds.add_value(speed)
        self.angles.add_value(angle)

    @abstractmethod
    def predicted_path(self):
        'Stores the predicted path into self.pred_path and returns it'
        pass

    def intercept_point(self):
        future_pos, future_vel = self.predicted_path()

        i_point = None
        for path in zip(future_pos[:-1], future_pos[1:]):
            i_point = self.defense_circle.intersect(path[0], path[1])
            if i_point:
                break

        return i_point

    def draw(self, frame):
        'Draws table and puck future positions using last predicted paths'

        # Draw predicted path
        for path in zip(self.pred_path[:-1], self.pred_path[1:]):
            p1 = tuple([int(p) for p in path[0]])
            p2 = tuple([int(p) for p in path[1]])
            cv2.line(frame,p1,p2,(255,0,0),5)

        # Draw defense circle
        self.defense_circle.draw(frame, (255, 0, 0))

class PyMunkPredictor(TableSimPredictor):

    def __init__(self, width, height, num_steps=10, **kwargs):
        super(PyMunkPredictor, self).__init__(width, height, **kwargs)

        self.table = sim_pymunk.AirHockeyTable(width, height)
        self.num_steps = num_steps

    def predicted_path(self):

        # Add a puck to the space and apply a speed at the determined
        # angle
        puck = self.table.add_puck(position=self.curr_pos)

        # Convert angle, speed averages tor regular floats, pymunk
        # doesn't seem to like numpy floats
        angle = float(self.angles.average)
        speed = float(self.speeds.average)

        impulse = speed * pymunk.Vec2d(1, 0).rotated(angle)
        puck.body.apply_impulse(impulse)

        # Simulate several steps into the future
        future_pos = []
        future_vel = []
        dt = 1.0/self.num_steps
        for t in range(self.num_steps):
            self.table.space.step(dt)
            future_pos.append(tuple(puck.body.position))
            future_vel.append(tuple(puck.body.velocity)) 

        # Remove the puck once the simulation is over
        self.table.remove_puck(puck)

        self.pred_path = future_pos
        self.pred_vel = future_vel

        return future_pos, future_vel

    def draw(self, frame):
        'Draws table and puck future positions using last predicted paths'

        super(PyMunkPredictor, self).draw(frame)

        # Draw simulated universe walls
        for line in self.table.walls:
            linea = tuple([int(a) for a in line.a])
            lineb = tuple([int(b) for b in line.b])
            cv2.rectangle(frame, linea, lineb, (255,0,0))


class Box2dPredictor(TableSimPredictor):

    def __init__(self, width, height, num_steps=10, **kwargs):
        super(Box2dPredictor, self).__init__(width, height, **kwargs)

        import game_box2d
        self.table = game_box2d.AirHockeyGame(width, height)
        self.num_steps = num_steps

    def predicted_path(self):

        puck = self.table.pucks[0]
        puck.position = ( self.curr_pos[0] / sim_box2d.PPM, self.curr_pos[1] / sim_box2d.PPM )

        # Convert angle, speed averages tor regular floats, pymunk
        # doesn't seem to like numpy floats
        angle = float(self.angles.average) 
        speed = float(self.speeds.average) / sim_box2d.PPM

        impulse = speed * b2Rot(angle).x_axis
        puck.linearVelocity = b2Vec2(0, 0)
        puck.ApplyLinearImpulse(impulse, puck.worldCenter, wake=True)

        # Simulate several steps into the future
        future_pos = []
        future_vel = []
        dt = 1.0/10
        for t in range(self.num_steps):
            self.table.world.Step(dt, 6, 2)
            p = puck.position
            future_pos.append( (p[0] * sim_box2d.PPM, p[1] * sim_box2d.PPM) )

        self.pred_path = future_pos
        self.pred_vel = future_vel

        return future_pos, future_vel

    def draw(self, frame):
        'Draws table and puck future positions using last predicted paths'
    
        super(Box2dPredictor, self).draw(frame)

        # Draw simulated universe walls
        for fixture in self.table.walls.fixtures:
            vertices = fixture.shape.vertices
            linea = tuple([int(a*sim_box2d.PPM) for a in vertices[0]])
            lineb = tuple([int(b*sim_box2d.PPM) for b in vertices[1]])
            cv2.rectangle(frame, linea, lineb, (255,0,0))
