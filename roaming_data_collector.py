# %%
# The following boilerplate is required if .egg is not installed
# See: https://carla.readthedocs.io/en/latest/build_system/
import glob
import os
import sys

try:
    sys.path.append(glob.glob('./carla-*%d.%d-%s.egg' % (
        sys.version_info.major,
        sys.version_info.minor,
        'win-amd64' if os.name == 'nt' else 'linux-x86_64'))[0])
except IndexError:
    pass

import argparse
import yaml
import carla
import re
import weakref
import random
import numpy as np
import matplotlib.pyplot as plt
import queue

# %% ================= Global function =================


def find_weather_presets():
    """ Method to find weather presets """
    rgx = re.compile('.+?(?:(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)')
    def name(x): return ' '.join(m.group(0) for m in rgx.finditer(x))
    presets = [x for x in dir(carla.WeatherParameters)
               if re.match('[A-Z].+', x)]
    return [(getattr(carla.WeatherParameters, x), name(x)) for x in presets]

# %% ================= Geo2Location =================


class Geo2Location(object):
    """
    Helper class for homogeneous transform from geolocation used by gnss to Cartisian location.
    This transform is not provided by Carla, but it can be solved using 4 chosen points.
    """

    def __init__(self, map):
        """ Constructor method """
        self._map = map
        # Pick 4 points of carla.Location
        loc1 = carla.Location(0, 0, 0)
        loc2 = carla.Location(1, 0, 0)
        loc3 = carla.Location(0, 1, 0)
        loc4 = carla.Location(0, 0, 1)
        # Get the corresponding carla.GeoLocation points using carla's transform_to_geolocation()
        geoloc1 = self._map.transform_to_geolocation(loc1)
        geoloc2 = self._map.transform_to_geolocation(loc2)
        geoloc3 = self._map.transform_to_geolocation(loc3)
        geoloc4 = self._map.transform_to_geolocation(loc4)
        # Solve the transform from geolocation to location (geolocation_to_location)
        l = np.array([[loc1.x, loc2.x, loc3.x, loc4.x],
                      [loc1.y, loc2.y, loc3.y, loc4.y],
                      [loc1.z, loc2.z, loc3.z, loc4.z],
                      [1, 1, 1, 1]], dtype=np.float)
        g = np.array([[geoloc1.latitude, geoloc2.latitude, geoloc3.latitude, geoloc4.latitude],
                      [geoloc1.longitude, geoloc2.longitude,
                          geoloc3.longitude, geoloc4.longitude],
                      [geoloc1.altitude, geoloc2.altitude,
                          geoloc3.altitude, geoloc4.altitude],
                      [1, 1, 1, 1]], dtype=np.float)
        # Tform = (G*L^-1)^-1
        self._tform = np.linalg.inv(g.dot(np.linalg.inv(l)))

    def transform(self, geolocation):
        """ 
        Transform from carla.GeoLocation to carla.Location.
        Numerical error may exist. Experiments show error is about under 1 cm in Town03.
        """
        geoloc = np.array(
            [geolocation.latitude, geolocation.longitude, geolocation.altitude, 1])
        loc = self._tform.dot(geoloc.T)
        return carla.Location(loc[0], loc[1], loc[2])

    def get_matrix(self):
        """ Get the 4-by-4 transform matrix """
        return self._tform


# %% ================= World =================


class World(object):
    """ Class representing the surrounding environment """

    def __init__(self, carla_world, traffic_manager, config_args):
        """ Constructor """
        self.carla_world = carla_world
        self.tm = traffic_manager
        self.spectator = carla_world.get_spectator()
        try:
            self.map = self.carla_world.get_map()
        except RuntimeError as error:
            print('RuntimeError: {}'.format(error))
            print('  The server could not send the OpenDRIVE (.xodr) file:')
            print(
                '  Make sure it exists, has the same name of your town, and is correct.')
            sys.exit(1)
        self._weather_presets = find_weather_presets()
        self._weather_index = config_args['world']['weather']
        self.carla_world.set_weather(
            self._weather_presets[self._weather_index][0])
        self.ego_veh = None
        self.imu = None
        self.gnss = None
        self.semantic_camera = None

        # Start simuation
        self.restart(config_args)

    def restart(self, config_args, spawn_point=None):
        # Set up carla engine using config
        settings = self.carla_world.get_settings()
        settings.no_rendering_mode = config_args['world']['no_rendering']
        settings.synchronous_mode = config_args['world']['sync_mode']
        settings.fixed_delta_seconds = config_args['world']['delta_seconds']
        self.carla_world.apply_settings(settings)

        # Spawn the ego vehicle as a cool mustang
        ego_veh_bp = self.carla_world.get_blueprint_library().find('vehicle.mustang.mustang')
        print("Spawning the ego vehicle.")
        if self.ego_veh is not None:
            # Destroy previously spawned actors
            self.destroy()
            if spawn_point is None:
                spawn_point = self.ego_veh.get_transform()
                spawn_point.location.z += 2.0
                spawn_point.rotation.roll = 0.0
                spawn_point.rotation.pitch = 0.0
                self.ego_veh = self.carla_world.try_spawn_actor(
                    ego_veh_bp, spawn_point)
            else:
                self.ego_veh = self.carla_world.try_spawn_actor(
                    ego_veh_bp, spawn_point)
                if self.ego_veh is None:
                    print('Chosen spawn transform failed.')

        while self.ego_veh is None:
            if not self.map.get_spawn_points():
                print('There are no spawn points available in your map/town.')
                sys.exit(1)
            spawn_points = self.map.get_spawn_points()
            spawn_point = random.choice(
                spawn_points) if spawn_points else carla.Transform()
            self.ego_veh = self.carla_world.try_spawn_actor(
                ego_veh_bp, spawn_point)

        # Point the spectator to the ego vehicle
        self.spectator.set_transform(carla.Transform(spawn_point.location + carla.Location(z=25),
                                                     carla.Rotation(pitch=-90)))

        # Set up the sensors
        self.gnss = GNSS(self.ego_veh, config_args['sensor']['gnss'])
        self.imu = IMU(self.ego_veh, config_args['sensor']['imu'])
        self.semantic_camera = SemanticCamera(
            self.ego_veh, config_args['sensor']['semantic_image'])

        # Tick the world to bring the actors into effect
        self.step_forward()

    def set_ego_autopilot(self, active, autopilot_config_args=None):
        """ Set traffic manager and register ego vehicle to it"""
        if autopilot_config_args is not None:
            self.tm.auto_lane_change(
                self.ego_veh, autopilot_config_args['auto_lane_change'])
            self.tm.ignore_lights_percentage(
                self.ego_veh, autopilot_config_args['ignore_lights_percentage'])
            self.tm.vehicle_percentage_speed_difference(
                self.ego_veh, autopilot_config_args['vehicle_percentage_speed_difference'])
        self.ego_veh.set_autopilot(active, self.tm.get_port())

    def step_forward(self):
        """ Tick carla world to take simulation one step forward"""
        self.carla_world.tick()
        self.imu.update()
        self.gnss.update()
        self.semantic_camera.update()

    def allow_free_run(self):
        """ Allow carla engine to run asynchronously and freely """
        settings = self.carla_world.get_settings()
        settings.synchronous_mode = False
        settings.fixed_delta_seconds = 0.0
        self.carla_world.apply_settings(settings)

    def destroy(self):
        """ Destroy spawned actors in carla world """
        if self.ego_veh is not None:
            print("Destroying the ego vehicle.")
            self.ego_veh.destroy()
            self.ego_veh = None
        if self.imu is not None:
            print("Destroying IMU sensor.")
            self.imu.destroy()
            self.imu = None
        if self.gnss is not None:
            print("Destroying gnss sensor.")
            self.gnss.destroy()
            self.gnss = None
        if self.semantic_camera is not None:
            print("Destroying semantic camera sensor.")
            self.semantic_camera.destroy()
            self.semantic_camera = None

# TODO: Simulate odometry and yaw rate


# %% ================= Sensor Base =================


class Sensor(object):
    """ Base class for sensors """

    def __init__(self, parent_actor):
        """ Constructor method """
        self.sensor = None
        self.timestamp = 0.0
        self._parent = parent_actor
        # The callback method in listen() to retrieve data used widely in official tutorials has a data race problem.
        # The callback will likely not finish before data get accessed from the main loop, causing inconsistent data.
        # Here the queue is expected to be used in listen() instead. The callback simply puts the sensor data into the queue,
        # then the data can be obtained in update() using get() which blocks and make sure synchronization.
        self._queue = queue.Queue()

    def update(self):
        """ Wait for sensro event to be put in queue and update data """
        raise NotImplementedError()

    def destroy(self):
        """ Destroy sensor actor """
        if self.sensor is not None:
            self.sensor.destroy()
            self.sensor = None


# %% ================= IMU Sensor =================


class IMU(Sensor):
    """ Class for IMU sensor"""

    def __init__(self, parent_actor, imu_config_args):
        """ Constructor method """
        super().__init__(parent_actor)
        self.accelerometer = None
        self.gyro = None

        world = self._parent.get_world()
        imu_bp = world.get_blueprint_library().find('sensor.other.imu')

        imu_bp.set_attribute('noise_accel_stddev_x',
                             imu_config_args['noise_accel_stddev_x'])
        imu_bp.set_attribute('noise_accel_stddev_y',
                             imu_config_args['noise_accel_stddev_y'])
        imu_bp.set_attribute('noise_accel_stddev_z',
                             imu_config_args['noise_accel_stddev_z'])
        imu_bp.set_attribute('noise_gyro_bias_x',
                             imu_config_args['noise_gyro_bias_x'])
        imu_bp.set_attribute('noise_gyro_bias_y',
                             imu_config_args['noise_gyro_bias_y'])
        imu_bp.set_attribute('noise_gyro_bias_z',
                             imu_config_args['noise_gyro_bias_z'])
        imu_bp.set_attribute('noise_gyro_stddev_x',
                             imu_config_args['noise_gyro_stddev_x'])
        imu_bp.set_attribute('noise_gyro_stddev_y',
                             imu_config_args['noise_gyro_stddev_y'])
        imu_bp.set_attribute('noise_gyro_stddev_z',
                             imu_config_args['noise_gyro_stddev_z'])

        print("Spawning IMU sensor.")
        self.sensor = world.spawn_actor(imu_bp, carla.Transform(carla.Location(x=0.0, z=0.0)),
                                        attach_to=self._parent)

        self.sensor.listen(lambda event: self._queue.put(event))

    def update(self):
        """ Wait for IMU measurement and update data """
        # get() blocks the script so synchronization is guaranteed
        event = self._queue.get()
        self.timestamp = event.timestamp
        self.accelerometer = event.accelerometer
        self.gyro = event.gyroscope


# %% ================= GNSS Sensor =================


class GNSS(Sensor):
    """ Class for GNSS sensor"""

    def __init__(self, parent_actor, gnss_config_args):
        """ Constructor method """
        super().__init__(parent_actor)
        self.lat = 0.0
        self.lon = 0.0
        self.alt = 0.0
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0

        world = self._parent.get_world()
        gnss_bp = world.get_blueprint_library().find('sensor.other.gnss')

        gnss_bp.set_attribute(
            'noise_alt_bias', gnss_config_args['noise_alt_bias'])
        gnss_bp.set_attribute('noise_alt_stddev',
                              gnss_config_args['noise_alt_stddev'])
        gnss_bp.set_attribute(
            'noise_lat_bias', gnss_config_args['noise_lat_bias'])
        gnss_bp.set_attribute('noise_lat_stddev',
                              gnss_config_args['noise_lat_stddev'])
        gnss_bp.set_attribute(
            'noise_lon_bias', gnss_config_args['noise_lon_bias'])
        gnss_bp.set_attribute('noise_lon_stddev',
                              gnss_config_args['noise_lon_stddev'])

        print("Spawning GNSS sensor.")
        self.sensor = world.spawn_actor(gnss_bp, carla.Transform(carla.Location(x=0.0, z=0.0)),
                                        attach_to=self._parent, attachment_type=carla.AttachmentType.Rigid)
        self._geo2location = Geo2Location(world.get_map())

        self.sensor.listen(lambda event: self._queue.put(event))

    def update(self):
        """ Wait for GNSS measurement and update data """
        # get() blocks the script so synchronization is guaranteed
        event = self._queue.get()
        self.timestamp = event.timestamp
        self.lat = event.latitude
        self.lon = event.longitude
        self.alt = event.altitude

        # Get transform from geolocation to location
        location = self._geo2location.transform(
            carla.GeoLocation(self.lat, self.lon, self.alt))
        self.x = location.x
        self.y = location.y
        self.z = location.z

# %% ================= Semantic Camera =================


class SemanticCamera(Sensor):
    """ Class for semantic camera """

    def __init__(self, parent_actor, ss_cam_config_args):
        """ Constructor method"""
        super().__init__(parent_actor)
        self.lane_img = None
        self.pole_img = None

        world = self._parent.get_world()
        ss_cam_bp = world.get_blueprint_library().find(
            'sensor.camera.semantic_segmentation')
        ss_cam_bp.set_attribute('image_size_x', ss_cam_config_args['res_x'])
        ss_cam_bp.set_attribute('image_size_y', ss_cam_config_args['res_y'])
        ss_cam_bp.set_attribute('fov', ss_cam_config_args['fov'])

        print("Spawning semantic camera sensor.")
        self.sensor = world.spawn_actor(ss_cam_bp, carla.Transform(carla.Location(x=0.6, z=1.5)),
                                        attach_to=self._parent)

        self.sensor.listen(lambda image: self._queue.put(image))

    def update(self):
        """ Wait for semantic image and update data """
        image = self._queue.get()
        self.timestamp = image.timestamp
        np_img = np.frombuffer(image.raw_data, dtype=np.uint8)
        # Reshap to BGRA format
        # Semantic info is stored only in the R channel
        np_img = np.reshape(np_img, (image.height, image.width, -1))
        # Lane lines and sidewalks are considered
        self.lane_img = (np_img[:, :, 2] == 6) | (np_img[:, :, 2] == 8)
        # Pole-like objects
        self.pole_img = np_img[:, :, 2] == 5

    def destroy(self):
        """ Destroy semantic camera actor """
        if self.sensor is not None:
            self.sensor.destroy()
            self.sensor = None

# %% ================= Ground Truth  =================


class GroundTruth(object):
    """ Class for ground truth extraction """

    def __init(self, config_args):
        pass


# %%
def main():
    # Parse passed-in config yaml file
    argparser = argparse.ArgumentParser(
        description='CARLA Roaming Data Collector')
    argparser.add_argument('config', type=argparse.FileType(
        'r'), help='configuration yaml file for carla env setup')
    args = argparser.parse_args()

    # Read configurations from yaml file to config_args
    with args.config as config_file:
        config_args = yaml.safe_load(config_file)

    # Initialize world
    world = None
    try:
        client = carla.Client('localhost', 2000)
        client.set_timeout(5.0)
        # Create a World obj with a built-in map
        world = World(client.load_world(
            config_args['world']['map']), client.get_trafficmanager(), config_args)

        # Launch autopilot for ego vehicle
        world.set_ego_autopilot(True, config_args['autopilot'])

        n_ticks = int(config_args['sim_duration'] /
                      config_args['world']['delta_seconds'])

        # Simulation loop
        for _ in range(n_ticks):
            world.step_forward()
            print(world.gnss.timestamp)
            print("EGO: {}, {}".format(world.ego_veh.get_location().x,
                                       world.ego_veh.get_location().y))
            print("GNSS: {}, {}".format(world.gnss.x, world.gnss.y))

    finally:
        if world is not None:
            world.set_ego_autopilot(False)
            world.destroy()
            # Allow carla engine to run freely so it doesn't just hang there
            world.allow_free_run()


# %%
if __name__ == '__main__':
    main()
