# QCM Data Collection and Analysis Software

This is the Python project page for the QCM data collection and analysis software used by the Shull research group at Northwestern University. The data collection and analysis are at the testing point. Curentlly, it is using it's own data format (hdf5). The data importing function will be added soon which will be useful to the community doing QCM-D test. Some of the analysis routines are potentially useful for the data in Matlab version, however, and these are described below.

## Getting Started

The analysis portions of the software should work on Windows/Mac/Linux platforms. In all cases you'll need some familiarity with running commands from the terminal, however.  It's assumed in the following that you know how to do this on your platform.  The software to interface with the network analyzers only runs on Windows-based computers.

### Functions

* Collecting data interfaces with network analyzers.  
* Communicate with analysers directy. Fast recording without openning the dependent external software. Less resources are required.  
* Combine data collection and analysis in one software.  
* Functioned with temperature recording. (with NI devices)

### Prerequisites

* Python 3.5+ is required. For data analysis only, it can run with both 32-bit and 64-bit Python. If you want the data collection with myVNA, 32-bit Python and Windows are required.  
* Hardware and external software for data collection: The AccessMyVNA and myVNA programs were obtained from http://g8kbb.co.uk/html/downloads.html.
* Python labroaries needed to run the software is listed in the `requirements.txt` file.  
* Anaconda platform is suggested Download and install the Anaconda distribution of python from [anaconda.com](https://anaconda.com/download).  
* QCM data files are currently stored in a MATLAB-compatible .mat files.  In order to read and write these and get the analysis scripts to work, you need to install the hdf5storage package, which you can add with the following command (assuming you have already added the conda python distribution):
```
conda install -c conda-forge hdf5storage 
```

### Installation

To install everything you need from this repository, run the following command from a command window in the directory where you want everthing to be installed:

```
git clone https://github.com/zhczq/QCM_py
```

If you just need the updated analysis software (which currently the only software that actually works) everything you really need is in QCMFuncs/QCM_functions.py.  In this same directory you will also find some example data obtained with polystyrene films at different temperatures, and a run file called PS_plots.py.  You should be able to run PS_plots.py directly and end up with some property plots that illustrate how the process works, and how you need to set up the file structure to include your own data.

## Using the Analysis Program

To see an example of how the program works, run example_runfile.py, which will act on some of the data in the example_data directory and generate some figures representing the analyzed data in a figures folder. 

## Documentation

The QCMnotes.pdf file has some background information on the rheometric mode of the QCM that we utilize, with some useful references include.

Modules `DataSaver` and `QCM` in Modules/ folder are availabe for dealing with the data and doing ananlysis manually. Those modules include functions run out of the software. You can simply import those modules and you can do almost the same thing in the software by running your own codes.

The functions for Matlab version data are locoalized in QCMFuncs/ folder.  

## To Do

* Documentation.
* Property results plotting and exporting.
* Data analysis with QCM-D data.
* Compile to runnable single file for those who doesn't want to run commond lines.
* Interface with other hardware. (If you have a hardware and interested in interfacing with our software, please feel free to contact us.)

## Authors

* **Qifeng Wang**  - *Primary Developer of the current (Python) version of this project*
* **Megan Yang**  - *Developer of the current (python) version of this project*
* **Kenneth R. Shull** - *Project PI and author of some of the specific functions used in the project*

## Other Versions

If you are a Matlab user, our long-term developed Matlab version software can be found here: https://github.com/Shull-Research-Group/QCM_Data_Acquisition_Program It is developed and being maintained by Josh Yeh. This Python project is developed based on the Matlab version.  

## Acknowledgments

* Josh Yeh
* Diethelm Johannsmann
* Lauren Sturdy
* Ivan Makarov
