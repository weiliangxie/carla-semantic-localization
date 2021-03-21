# SMMPDA

This repo implements Semantic Max-mixture Probabilistic Data Association localization using the miniSAM library. Simulations are conducted with CARLA. Ubuntu 18.04 LTS has been used to develop this project.

## Environment Setup
Using miniconda is recommended beause this repo is developed this way. The repo comes with an [environment.yml](environment.yml) file that facilitates setting up the environment.

To create the same conda environment with the default name "__smmpda__":
```
conda env create -f environment.yml
```
Refer to [Creating an environment from an environment.yml file](https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html#creating-an-environment-from-an-environment-yml-file) for more info.

## Dependencies
This project depends on CARLA and miniSAM, which need to be installed manually in addition to the conda environment. Follow their official guides for proper installation.

[CARLA](http://carla.org/)  
The version __0.9.10__ is used throughout this repo. The corresponding .egg file has be included in the root directory of this repo. To upgrade, replace the .egg file with a newer version. CARLA suggests two ways to import PythonAPIs as written in [here](https://carla.readthedocs.io/en/latest/build_system/). The first inelegant method by adding the .egg file to the system path is used because _easy_install_ seems to be deprecated ([ref1](https://setuptools.readthedocs.io/en/latest/deprecated/easy_install.html), [ref2](https://workaround.org/easy-install-debian)).

[miniSAM](https://minisam.readthedocs.io/index.html)  
Follow the instructions in [C++ Compile and Installation](https://minisam.readthedocs.io/install.html) and [Python Installation](https://minisam.readthedocs.io/install_python.html) to install the miniSAM library. Some additional dependencies are required by miniSAM. Make sure to activate the correct conda environment when installing the miniSAM Python package, so it is installed in the correct conda environment.

## Install SMMPDA Package
This repo comes with a [setup.py](setup.py) file that wraps this project into an installable Python package. Once the project is installed, the library can be imported easily in a Python module. This makes testing more convenient. ([ref](https://stackoverflow.com/questions/6323860/sibling-package-imports/50193944#50193944))

To install the smmpda package in _develop_ mode:
```
cd [PATH_TO_REPO]
pip install -e .
```

## Quick Start
Three tasks are performed individually. Remember to activate the correct conda environment.

### 1. Collect data in CARLA with a predefined path.
Launch CARLA, then run:
```
python -O raw_collector.py settings/carlasim.yaml -r
```
This spawns a Mustang (yes, I'm old-school) in the CARLA world with sensors, which wanders around and collects data from the sensors. The ```-O``` flag turns on the optimization mode of python interpretor and turns off debug features. When runing without this flag, some shapes will be drawn in the CARLA world, e.g. lane boundaries points, for debug's purpose. 

The first argument is the configuration YAML file that defines all details regarding CARLA simulation, such as the used map, the weather, how the car is controlled, and sensor configurations. The folder [settings](settings) contains a [carlasim.yaml](settings/carlasim.yaml) that can be used for quick tests. See comments in the files for more information on how to set the parameters. If a sensor noise parameter is set as 0, CARLA simply gives you the ground truth value for the corresponding measurement. In the folder [settings/routes](settings/routes), several pre-defined config files can be found, which only differ in their used waypoints.

The flag ```-r``` turns on the saving of the recorded data specified in the configuration file mentioned above. A __recordings__ folder will be created in the root of this project the first time, under which the recorded data of a simulation will be saved into a folder named by the time the simulation is run. It is recommended to change the folder name to something more meaningful right after saving. Data are stored into 3 files:
1. sensor_data.pkl: Simulated raw sensor data.
2. gt_data.pkl: Ground truth data.
3. carla_recording.log: Data for CARLA replay. Refer to [here](https://carla.readthedocs.io/en/0.9.10/adv_recorder/).

Besides recordings, a copy of the used CARLA simulation configuration file named __config.yaml__ is saved in the folder __settings__ under the same folder for future reference.

### 2. Generate simulated object-level detections
Say you have saved the collected data in __recordings/test__ in the first step, generate simulated detections and the pole map for it by:
```
python -O detection_generator.py recordings/test settings/vision.yaml settings/sim_detection.yaml setting/pole_map.yaml
```
Running it without the ```-O``` flag will show the visualization of the generated pole map in the end. The first argument is the folder of the recording. The file __vision.yaml__ defines parameters regarding vision-based detection algorithms. __sim_detection.yaml__ defines parameters regarding data generated based on GT data, which are more artificial compared to the vision-based part. __pole_map.yaml__ defines parameters that are used for pole map generation. See the comments in them for more information. It took me some time to tune the parameters, but feel free to fine-tune them.

The results will be saved into 2 files under the same folder as the recorded data:
1. detections.pkl: Simulated detections.
2. pole_map.pkl: Generated pole map.

The 3 above-mentioned configuration files are also copied into the __settings__ folder under the same recording folder for future reference.

After generating simulated detections, you can visualize the result by:
```
python detection_viewer.py recordings/test
```

### 3. Run SMMPDA localization on simulated data
