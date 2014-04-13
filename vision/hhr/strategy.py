import math

import cv2
import pymunk

from .sim import AirHockeyTable
from .interface import PuckPredictor
from .calc import MovingAverage

def calculate_speed_angle(pos1, pos2, time1, time2):
    del_y = pos2[1] - pos1[1]
    del_x = pos2[0] - pos1[0]
    del_time = (time2 - time1) / cv2.getTickFrequency()

    angle = math.atan2(del_y, del_x)
    speed = math.sqrt(del_x * del_x + del_y * del_y) / del_time 

    return speed, angle

class TableSimPredictor(PuckPredictor):

    def __init__(self, threshold, width, height, num_steps=10, avg_size=10):
        self.table = AirHockeyTable(width, height)
        self._threshold = threshold
        self.num_steps = num_steps

        # Store current posistion and time 
        self.curr_pos = (0, 0)
        self.curr_time = 0

        # Cache predicted path for draw
        self.pred_path = []

        # Calculate angles and speeds as we get them so we
        # can keep a rolling sum 
        self.angles = MovingAverage(avg_size)
        self.speeds = MovingAverage(avg_size) 

    def threshold(self):
        return self._threshold

    def add_puck_event(self, tick, coords, radius):

        last_pos = self.curr_pos
        last_time = self.curr_time

        self.curr_pos = coords
        self.curr_time = tick

        speed, angle = calculate_speed_angle(last_pos, self.curr_pos, last_time, self.curr_time)

        self.speeds.add_value(speed)
        self.angles.add_value(angle)

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

        return future_pos, future_vel

    def draw(self, frame):
        'Draws table and puck future posistions using last predicted paths'

        for path in zip(self.pred_path[:-1], self.pred_path[1:]):
            p1 = tuple([int(p) for p in path[0]])
            p2 = tuple([int(p) for p in path[1]])
            cv2.line(frame,p1,p2,(255,0,0),5)

        # Draw simulated universe walls
        for line in self.table.walls:
            linea = tuple([int(a) for a in line.a])
            lineb = tuple([int(b) for b in line.b])
            cv2.rectangle(frame, linea, lineb, (255,0,0))

