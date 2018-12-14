'''
This is the main code of the QCM acquization program
'''

import os
import subprocess
# import csv
# import importlib
import math
import json
import shutil
import datetime, time
import numpy as np
import pandas as pd
import scipy.signal
# import types
from PyQt5.QtCore import pyqtSlot, Qt, QEvent, QTimer, QEventLoop
from PyQt5.QtWidgets import (
    QApplication, QWidget, QMainWindow, QFileDialog, QActionGroup, QComboBox, QCheckBox, QTabBar, QTabWidget, QVBoxLayout, QGridLayout, QLineEdit, QCheckBox, QComboBox, QSpinBox, QRadioButton, QMenu, QAction, QMessageBox, QTableWidgetItem
)
from PyQt5.QtGui import QIcon, QPixmap, QMouseEvent, QValidator, QIntValidator, QDoubleValidator, QRegExpValidator

# packages
from MainWindow import Ui_MainWindow
from UISettings import settings_init, settings_default
from modules import UIModules, GBFitting, PeakTracker, DataSaver, QCM
from modules.MatplotlibWidget import MatplotlibWidget

import _version

 

if UIModules.system_check() == 'win32': # windows
    import struct
    if struct.calcsize('P') * 8 == 32: # 32-bit version Python
        try:
            # from modules.AccessMyVNA_dummy import AccessMyVNA
            from modules.AccessMyVNA_np import AccessMyVNA
            print(AccessMyVNA)
            # test if MyVNA program is available
            with AccessMyVNA() as vna:
                if vna.Init() == 0: # connection with myVNA is available
                    try:
                        from modules import TempDevices,TempModules
                    except Exception as e:
                        print('Failed to import TempDevices and/or TempModules.\nTemperature functions of the UI will not avaiable!')

        except Exception as e: # no myVNA connected. Analysis only
            print('Failed to import AccessMyVNA module!')
            print(e)
    else: # 64-bit version Python which doesn't work with AccessMyVNA
        # A 32-bit server may help 64-bit Python work with 32-bit dll
        print('Current version of MyVNA does not work with 64-bit Python!\nData analysis only!')
else: # linux or MacOS
    # for test only
    # from modules.AccessMyVNA_dummy import AccessMyVNA
        print('Current version of MyVNA does not work with MacOS and Linux!\nData analysis only!')


class VNATracker:
    def __init__(self):
        self.f =None       # current end frequency span in Hz (ndarray([float, float])
        self.steps = None   # current number of steps (int)
        self.chn = None     # current reflection ADC channel (1 or 2)
        self.avg = None     # average of scans (int)
        self.speed = None   # vna speed set up (int 1 to 10)
        self.instrmode = 0  # instrument mode (0: reflection)
        
        self.setflg = {} # if vna needs to reset (set with reset selections)
        self.setflg.update(self.__dict__) # get all attributes in a dict
        self.setflg.pop('setflg', None) # remove setflg itself
        # print(self.setflg)
    
    def set_check(self, **kwargs):
        for key, val in kwargs.items():
            print(key, val)
            print(type(val))
            if isinstance(val, np.ndarray): # self.f 
                val = val.tolist()
                # if not np.array_equal(val, getattr(self, key)): # if self.<key> changed
                #     setattr(self, key, val) # save val to class
                # self.setflg[key] = val # add set key and value to setflg
            # else:
            if getattr(self, key) != val: # if self.<key> changed
                setattr(self, key, val) # save val to class
            self.setflg[key] = val # add set key and value to setflg

        return self.setflg

    def reset_flag(self):
        ''' set to vna doesn't neet rest '''
        self.setflg = {}


class QCMApp(QMainWindow):
    '''
    The settings of the app is stored in a dict by widget names
    '''
    def __init__(self):
        super(QCMApp, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.tempPath = '' # to store the file name before it is initiated
        self.settings = settings_default.copy() # import default settings. It will be initalized latter
        self.peak_tracker = PeakTracker.PeakTracker()
        self.vna_tracker = VNATracker()
        self.qcm = QCM.QCM()
  
        # define instrument state variables

        self.UITab = 0 # 0: Control; 1: Settings;, 2: Data; 3: Mechanics
        #### initialize the attributes for data saving
        self.data_saver = DataSaver.DataSaver(ver=_version.__version__, settings_init=settings_init)
        
        self.vna = None # vna class
        self.temp_sensor = None # class for temp sensor
        self.idle = True # if test is running
        self.reading = False # if myVNA/tempsensor is scanning and reading data
        self.writing = False # if UI is saving data
        self.counter = 0 # for counting the saving interval
        
        self.settings_harm = '1' # active harmonic in Settings Tab
        self.settings_chn = {'name': 'samp', 'chn': '1'} # active channel 'samp' or 'ref' in Settings Tab
        self.active = {} # active factors e.g.: harm, chnn_name, plt_str, ind, 
        self.mech_chn = 'samp'
        self.chn_set_store = {} # used for storing the channal setup self.settings.freq_span and self.settings.harmdata during manual refit
        self.prop_plot_list = [] # a list to store handles of prop plots


        # check system
        self.system = UIModules.system_check()
        # initialize AccessMyVNA
        #TODO add more code to disable settings_control tab and widges in settings_settings tab
        if self.system == 'win32': # windows
            try:
                # test if MyVNA program is available
                with AccessMyVNA() as vna:
                    if vna.Init() == 0: # is available
                        self.vna = AccessMyVNA() # save class AccessMyVNA to vna
                    else: # not available
                        pass
                print(vna)
            except:
                print('Initiating MyVNA failed!\nMake sure analyser is connected and MyVNA is correctly installed!')

        else: # other system, data analysis only
            # self.vna = AccessMyVNA() # for test only
            pass
        print(self.vna)

        # does it necessary???
        # if self.vna is not None: # only set the timer when vna is available
        # initiate a timer for test
        self.timer = QTimer()
        # self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.data_collection)

        # initiate a timer for progressbar
        self.bartimer = QTimer()
        self.bartimer.timeout.connect(self.update_progressbar)


        self.main()
        
        # hide widges not necessary
        self.hide_widgets(
            'version_hide_list'
        )

        # hide widgets not for analysis mode
        if self.vna is None:
            self.hide_widgets(
                'analysis_mode_disable_list'
            )

        self.load_settings()


    def main(self):
        #region ###### initiate UI #################################

        #region main UI 
        # link tabWidget_settings and stackedWidget_spectra and stackedWidget_data
        self.ui.tabWidget_settings.currentChanged.connect(self.link_tab_page)

        #endregion


        #region cross different sections
        # harmonic widgets
        # loop for setting harmonics 
        for i in range(1, settings_init['max_harmonic']+2, 2):
            # set to visable which is default. nothing to do

            # set all frame_sp<n> hided
            getattr(self.ui, 'frame_sp' +str(i)).setVisible(False)

            # add checkbox to tabWidget_ham for harmonic selection
            setattr(self.ui, 'checkBox_tree_harm' + str(i), QCheckBox())
            self.ui.tabWidget_settings_settings_harm.tabBar().setTabButton(
                self.ui.tabWidget_settings_settings_harm.indexOf(
                    getattr(self.ui, 'tab_settings_settings_harm' + str(i))
                ), 
                QTabBar.LeftSide, 
                getattr(self.ui, 'checkBox_tree_harm' + str(i)
                )
            )

            # set signal
            getattr(self.ui, 'checkBox_tree_harm' + str(i)).toggled['bool'].connect(
                getattr(self.ui, 'checkBox_harm' + str(i)).setChecked
            )
            getattr(self.ui, 'checkBox_harm' + str(i)).toggled['bool'].connect(
                getattr(self.ui, 'checkBox_tree_harm' + str(i)).setChecked
            )
            # getattr(self.ui, 'checkBox_tree_harm' + str(i)).toggled['bool'].connect(
            #     getattr(self.ui, 'frame_sp' +str(i)).setVisible
            # )
            getattr(self.ui, 'checkBox_harm' + str(i)).toggled['bool'].connect(
                getattr(self.ui, 'frame_sp' +str(i)).setVisible
            )

            getattr(self.ui, 'checkBox_harm' + str(i)).toggled['bool'].connect(self.update_widget)

            # checkBox_nhplot<n>
            getattr(self.ui, 'checkBox_nhplot' + str(i)).toggled.connect(self.update_widget)

        # show samp & ref related widgets 
        self.setvisible_samprefwidgets(samp_value=True, ref_value=False)

        # set comboBox_plt1_optsy/x, comboBox_plt2_optsy/x
        # dict for the comboboxes
        for key, val in settings_init['data_plt_opts'].items():
            # userData is setup for geting the plot type
            # userDat can be access with itemData(index)
            self.ui.comboBox_plt1_optsy.addItem(val, key)
            self.ui.comboBox_plt1_optsx.addItem(val, key)
            self.ui.comboBox_plt2_optsy.addItem(val, key)
            self.ui.comboBox_plt2_optsx.addItem(val, key)

        # set RUN/STOP button
        self.ui.pushButton_runstop.toggled.connect(self.on_clicked_pushButton_runstop)

        # set arrows (la and ra) to change pages 
        self.ui.pushButton_settings_la.clicked.connect(
            lambda: self.set_stackedwidget_index(self.ui.stackedWidget_spectra, diret=-1)
        ) # set index-1
        self.ui.pushButton_settings_ra.clicked.connect(
            lambda: self.set_stackedwidget_index(self.ui.stackedWidget_spectra, diret=1)
        ) # set index+1
        self.ui.pushButton_data_la.clicked.connect(
            lambda: self.set_stackedwidget_index(self.ui.stackedWidget_data, diret=-1)
        ) # set index -1
        self.ui.pushButton_data_ra.clicked.connect(
            lambda: self.set_stackedwidget_index(self.ui.stackedWidget_data, diret=1)
        ) # set index 1

        #endregion


        #region settings_control
        # set lineEdit_startf<n> & lineEdit_endf<n> & lineEdit_startf<n>_r & lineEdit_endf<n>_r background
        for i in range(1, settings_init['max_harmonic']+2, 2):
            getattr(self.ui, 'lineEdit_startf' + str(i)).setStyleSheet(
                "QLineEdit { background: transparent; }"
            )
            getattr(self.ui, 'lineEdit_endf' + str(i)).setStyleSheet(
                "QLineEdit { background: transparent; }"
            )
            getattr(self.ui, 'lineEdit_startf' + str(i) + '_r').setStyleSheet(
                "QLineEdit { background: transparent; }"
            )
            getattr(self.ui, 'lineEdit_endf' + str(i) + '_r').setStyleSheet(
                "QLineEdit { background: transparent; }"
            )

        # dateTimeEdit_reftime on dateTimeChanged
        self.ui.dateTimeEdit_reftime.dateTimeChanged.connect(self.on_dateTimeChanged_dateTimeEdit_reftime)
        # set pushButton_resetreftime
        self.ui.pushButton_resetreftime.clicked.connect(self.reset_reftime)

        # set lineEdit_scaninterval value
        self.ui.lineEdit_recordinterval.editingFinished.connect(self.set_lineEdit_scaninterval)
        self.ui.lineEdit_refreshresolution.editingFinished.connect(self.set_lineEdit_scaninterval)

        # add value to the comboBox_settings_control_dispmode
        for key, val in settings_init['display_opts'].items():
            self.ui.comboBox_settings_control_dispmode.addItem(val, key)
        self.ui.comboBox_settings_control_dispmode.currentIndexChanged.connect(self.update_widget)
        self.ui.comboBox_settings_control_dispmode.currentIndexChanged.connect(self. update_freq_display_mode)

        # set pushButton_gotofolder
        self.ui.pushButton_gotofolder.clicked.connect(self.on_clicked_pushButton_gotofolder)

        # set pushButton_newfile
        self.ui.pushButton_newfile.clicked.connect(self.on_triggered_new_exp)

        # set pushButton_appendfile
        self.ui.pushButton_appendfile.clicked.connect(self.on_triggered_load_exp)

        # set lineEdit_scaninterval background
        self.ui.lineEdit_scaninterval.setStyleSheet(
            "QLineEdit { background: transparent; }"
        )

        self.ui.checkBox_dynamicfit.stateChanged.connect(self.update_widget)
        self.ui.spinBox_fitfactor.valueChanged.connect(self.update_widget)
        self.ui.checkBox_dynamicfitbyharm.clicked['bool'].connect(self.update_widget)
        self.ui.checkBox_fitfactorbyharm.clicked['bool'].connect(self.update_widget)

        # set signals to update spectra show display options
        self.ui.radioButton_spectra_showGp.toggled.connect(self.update_widget)
        self.ui.radioButton_spectra_showGp.clicked.connect(self.mpl_sp_clr_lines_set_label)
        self.ui.radioButton_spectra_showBp.toggled.connect(self.update_widget)
        self.ui.radioButton_spectra_showBp.clicked.connect(self.mpl_sp_clr_lines_set_label)
        self.ui.radioButton_spectra_showpolar.toggled.connect(self.update_widget)
        self.ui.radioButton_spectra_showpolar.clicked.connect(self.mpl_sp_clr_lines_set_label)
        self.ui.checkBox_spectra_showchi.toggled.connect(self.update_widget)
        self.ui.checkBox_spectra_showchi.toggled.connect(self.mpl_sp_clr_chis)

        # set signals to checkBox_control_rectemp
        self.ui.checkBox_control_rectemp.clicked['bool'].connect(self.on_clicked_set_temp_sensor)

        # set checkBox_dynamicfitbyharm
        self.ui.checkBox_dynamicfitbyharm.clicked['bool'].connect(self.on_clicked_checkBox_dynamicfitbyharm)

        # set checkBox_fitfactorbyharm
        self.ui.checkBox_fitfactorbyharm.clicked['bool'].connect(self.on_clicked_checkBox_fitfactorbyharm)

        # set lineEdit_datafilestr background
        self.ui.lineEdit_datafilestr.setStyleSheet(
            "QLineEdit { background: transparent; }"
        )

        #endregion


        #region settings_settings


        # set signal
        self.ui.tabWidget_settings_settings_samprefchn.currentChanged.connect(self.update_widget)
        self.ui.tabWidget_settings_settings_samprefchn.currentChanged.connect(self.update_settings_chn)

        # remove tab_settings_settings_harmchnrefit from index
        self.add_manual_refit_tab(False)

        ### add combobox into treewidget
        self.ui.tabWidget_settings_settings_harm.currentChanged.connect(self.update_harmonic_tab)
        # move lineEdit_scan_harmstart
        self.move_to_col2(
            self.ui.lineEdit_scan_harmstart,
            self.ui.treeWidget_settings_settings_harmtree,
            'Start',
            100,
        )

        # move lineEdit_scan_harmend
        self.move_to_col2(
            self.ui.lineEdit_scan_harmend,
            self.ui.treeWidget_settings_settings_harmtree,
            'End',
            100,
        )

        # move lineEdit_scan_harmsteps
        self.move_to_col2(
            self.ui.lineEdit_scan_harmsteps,
            self.ui.treeWidget_settings_settings_harmtree,
            'Steps',
            100,
        )

        # move frame_peaks_num
        self.move_to_col2(
            self.ui.frame_peaks_num,
            self.ui.treeWidget_settings_settings_harmtree,
            'Num.',
            160,
        )

        # move frame_peaks_policy
        self.move_to_col2(
            self.ui.frame_peaks_policy,
            self.ui.treeWidget_settings_settings_harmtree,
            'Policy',
            160,
        )

        # move lineEdit_peaks_threshold
        self.move_to_col2(
            self.ui.lineEdit_peaks_threshold,
            self.ui.treeWidget_settings_settings_harmtree,
            'Threshold',
            100,
        )

        # move lineEdit_peaks_prominence
        self.move_to_col2(
            self.ui.lineEdit_peaks_prominence,
            self.ui.treeWidget_settings_settings_harmtree,
            'Prominence',
            100,
        )

        # move checkBox_harmfit
        self.move_to_col2(
            self.ui.checkBox_harmfit,
            self.ui.treeWidget_settings_settings_harmtree,
            'Fit',
            100,
        )

        # move spinBox_harmfitfactor
        self.move_to_col2(
            self.ui.spinBox_harmfitfactor,
            self.ui.treeWidget_settings_settings_harmtree,
            'Factor',
            100,
        )

        # set max value availabe
        self.ui.spinBox_harmfitfactor.setMaximum(settings_init['fitfactor_max'])

        # comboBox_tracking_method
        self.create_combobox(
            'comboBox_tracking_method', 
            settings_init['span_mehtod_opts'], 
            100, 
            'Method', 
            self.ui.treeWidget_settings_settings_harmtree
        )

        # add span track_method
        self.create_combobox(
            'comboBox_tracking_condition', 
            settings_init['span_track_opts'], 
            100, 
            'Condition', 
            self.ui.treeWidget_settings_settings_harmtree
        )


        # insert samp_channel
        self.create_combobox(
            'comboBox_samp_channel', 
            settings_init['vna_channel_opts'], 
            100, 
            'S Channel', 
            self.ui.treeWidget_settings_settings_hardware
        )

        # inser ref_channel
        self.create_combobox(
            'comboBox_ref_channel', 
            settings_init['vna_channel_opts'], 
            100, 
            'R Channel', 
            self.ui.treeWidget_settings_settings_hardware
        )
        # connect ref_channel
        # self.ui.comboBox_ref_channel.currentIndexChanged.connect() #TODO add function checking if sample and ref have the same channel

        # insert base_frequency
        self.create_combobox(
            'comboBox_base_frequency', 
            settings_init['base_frequency_opts'], 
            100, 
            'Base Frequency', 
            self.ui.treeWidget_settings_settings_hardware
        )

        # insert bandwidth
        self.create_combobox(
            'comboBox_bandwidth', 
            settings_init['bandwidth_opts'], 
            100, 
            'Bandwidth', 
            self.ui.treeWidget_settings_settings_hardware
        )

        # add comBox_tempmodule to treeWidget_settings_settings_hardware
        try: 
            settings_init['temp_class_opts_list'] = TempModules.class_list # when TempModules is loaded
        except:
            settings_init['temp_class_opts_list'] = None # no temp module is loaded
        self.create_combobox(
            'comboBox_tempmodule',
            # UIModules.list_modules(TempModules),  
            settings_init['temp_class_opts_list'],  
            100,
            'Module',
            self.ui.treeWidget_settings_settings_hardware, 
        )
        self.settings['comboBox_tempmodule'] = self.ui.comboBox_tempmodule.itemData(self.ui.comboBox_tempmodule.currentIndex())
        self.ui.comboBox_tempmodule.activated.connect(self.update_widget)

        # add comboBox_tempdevice to treeWidget_settings_settings_hardware
        if self.vna and self.system == 'win32':
            settings_init['tempdevs_opts'] = TempDevices.dict_available_devs(settings_init['tempdevices_dict'])
            self.create_combobox(
                'comboBox_tempdevice',
                settings_init['tempdevs_opts'],  
                100,
                'Device',
                self.ui.treeWidget_settings_settings_hardware, 
            )
            self.settings['comboBox_tempdevice'] = self.ui.comboBox_tempdevice.itemData(self.ui.comboBox_tempdevice.currentIndex())
            self.ui.comboBox_tempdevice.currentIndexChanged.connect(self.update_tempdevice)
        else: # vna is not available
            self.create_combobox(
                'comboBox_tempdevice',
                [],  # an empty list
                100,
                'Device',
                self.ui.treeWidget_settings_settings_hardware, 
            )
            self.settings['comboBox_tempdevice'] = None # set to None 

        # insert thrmcpl type
        self.create_combobox(
            'comboBox_thrmcpltype', 
            settings_init['thrmcpl_opts'], 
            100, 
            'Thrmcpl Type', 
            self.ui.treeWidget_settings_settings_hardware
        )

        if not self.settings['comboBox_tempdevice']: # vna or tempdevice are not availabel
            # set temp related widgets unavailable
            self.disable_widgets(
                'temp_device_setting_disable_list',
                'temp_settings_enable_disable_list',
            )


        # insert time_unit
        self.create_combobox(
            'comboBox_timeunit', 
            settings_init['time_unit_opts'], 
            100, 
            'Time Unit', 
            self.ui.treeWidget_settings_settings_plots
        )

        # insert temp_unit
        self.create_combobox(
            'comboBox_tempunit', 
            settings_init['temp_unit_opts'], 
            100, 
            'Temp. Unit', 
            self.ui.treeWidget_settings_settings_plots
        )

        # insert X Scale
        self.create_combobox(
            'comboBox_xscale', 
            settings_init['scale_opts'], 
            100, 
            'X Scale', 
            self.ui.treeWidget_settings_settings_plots
        )

        # insert gamma scale
        self.create_combobox(
            'comboBox_yscale', 
            settings_init['scale_opts'], 
            100, 
            'Y Scale', 
            self.ui.treeWidget_settings_settings_plots
        )

        # move checkBox_linkx to treeWidget_settings_settings_plots
        self.move_to_col2(
            self.ui.checkBox_linkx, 
            self.ui.treeWidget_settings_settings_plots, 
            'Link Time'
        )

        # set treeWidget_settings_settings_harmtree expanded
        self.ui.treeWidget_settings_settings_harmtree.expandToDepth(0)
        # set treeWidget_settings_settings_hardware expanded
        self.ui.treeWidget_settings_settings_hardware.expandToDepth(0)
        # set treeWidget_settings_settings_plots expanded
        self.ui.treeWidget_settings_settings_plots.expandToDepth(0)


        # move center pushButton_settings_harm_cntr to treeWidget_settings_settings_harmtree
        self.move_to_col2(
            self.ui.pushButton_settings_harm_cntr, 
            self.ui.treeWidget_settings_settings_harmtree, 
            'Scan', 
            50
        )
        
        # move center checkBox_settings_temp_sensor to treeWidget_settings_settings_hardware
        self.move_to_col2(
            self.ui.checkBox_settings_temp_sensor, 
            self.ui.treeWidget_settings_settings_hardware, 
            'Temperature'
        )

        # set tabWidget_settings background
        self.ui.tabWidget_settings.setStyleSheet(
            # "QTabWidget, QTabWidget::pane, QTabBar { background: transparent; }"
            "QTabWidget::pane { border: 0;}"
            # "QTabWidget, QTabWidget::pane, QTabBar { border-width: 5px; border-color: red; }"
            # "QTabBar::tab-bar { background: transparent; }"
        )

        # set treeWidget_settings_settings_harmtree background
        self.ui.treeWidget_settings_settings_harmtree.setStyleSheet(
            "QTreeWidget { background: transparent; }"
        )
        # set treeWidget_settings_settings_hardware background
        self.ui.treeWidget_settings_settings_hardware.setStyleSheet(
            "QTreeWidget { background: transparent; }"
        )
        
        # set treeWidget_settings_settings_plots background
        self.ui.treeWidget_settings_settings_plots.setStyleSheet(
            "QTreeWidget { background: transparent; }"
        )

        # resize the TabBar.Button
        self.ui.tabWidget_settings_settings_harm.setStyleSheet(
            "QTabWidget::pane { height: 0; border: 0px; }"
            "QTabWidget {background-color: transparent;}"
            "QTabWidget::tab-bar { left: 5px; /* move to the right by 5px */ }"
            "QTabBar::tab { border: 1px solid #9B9B9B; border-top-left-radius: 1px; border-top-right-radius: 1px;}"
            "QTabBar::tab { height: 20px; width: 42px; padding: 0px; }" 
            "QTabBar::tab:selected, QTabBar::tab:hover { background: white; }"
            "QTabBar::tab:selected { height: 22px; width: 44px; border-bottom-color: none; }"
            "QTabBar::tab:selected { margin-left: -2px; margin-right: -2px; }"
            "QTabBar::tab:first:selected { margin-left: 0; width: 40px; }"
            "QTabBar::tab:last:selected { margin-right: 0; width: 40px; }"
            "QTabBar::tab:!selected { margin-top: 2px; }"
            )

        self.ui.lineEdit_recordinterval.setValidator(QDoubleValidator(0, math.inf, 6))
        self.ui.lineEdit_refreshresolution.setValidator(QIntValidator(0, 2147483647))
        self.ui.lineEdit_scan_harmstart.setValidator(QDoubleValidator(1, math.inf, 6))
        self.ui.lineEdit_scan_harmend.setValidator(QDoubleValidator(1, math.inf, 6))
        self.ui.lineEdit_scan_harmsteps.setValidator(QIntValidator(0, 2147483647))
        self.ui.lineEdit_peaks_threshold.setValidator(QDoubleValidator(0, math.inf, 6))
        self.ui.lineEdit_peaks_prominence.setValidator(QDoubleValidator(0, math.inf, 6))

        # set signals of widgets in tabWidget_settings_settings_harm
        self.ui.lineEdit_scan_harmstart.editingFinished.connect(self.on_editingfinished_harm_freq)
        self.ui.lineEdit_scan_harmend.editingFinished.connect(self.on_editingfinished_harm_freq)
        self.ui.comboBox_base_frequency.currentIndexChanged.connect(self.update_base_freq)
        self.ui.comboBox_bandwidth.currentIndexChanged.connect(self.update_bandwidth)

        # set signals to update span settings_settings
        self.ui.lineEdit_scan_harmsteps.textEdited.connect(self.update_harmwidget)
        self.ui.comboBox_tracking_method.activated.connect(self.update_harmwidget)
        self.ui.comboBox_tracking_condition.activated.connect(self.update_harmwidget)
        self.ui.checkBox_harmfit.toggled['bool'].connect(self.update_harmwidget)
        self.ui.spinBox_harmfitfactor.valueChanged.connect(self.update_harmwidget)
        self.ui.spinBox_peaks_num.valueChanged.connect(self.update_harmwidget)
        self.ui.lineEdit_peaks_threshold.textEdited.connect(self.update_harmwidget)
        self.ui.lineEdit_peaks_prominence.textEdited.connect(self.update_harmwidget)
        self.ui.radioButton_peaks_num_max.toggled['bool'].connect(self.update_harmwidget)
        self.ui.radioButton_peaks_num_fixed.toggled['bool'].connect(self.update_harmwidget)
        self.ui.radioButton_peaks_policy_minf.toggled['bool'].connect(self.update_harmwidget)
        self.ui.radioButton_peaks_policy_maxamp.toggled['bool'].connect(self.update_harmwidget)
    
        # set signals to update hardware settings_settings
        self.ui.comboBox_samp_channel.currentIndexChanged.connect(self.update_widget)
        self.ui.comboBox_samp_channel.currentIndexChanged.connect(self.update_vnachannel)
        self.ui.comboBox_samp_channel.currentIndexChanged.connect(self.update_settings_chn)
        self.ui.comboBox_ref_channel.currentIndexChanged.connect(self.update_widget)
        self.ui.comboBox_ref_channel.currentIndexChanged.connect(self.update_vnachannel)
        self.ui.comboBox_ref_channel.currentIndexChanged.connect(self.update_settings_chn)

        # self.ui.checkBox_settings_temp_sensor.stateChanged.connect(self.update_tempsensor)
        self.ui.checkBox_settings_temp_sensor.stateChanged.connect(self.on_clicked_set_temp_sensor)
        self.ui.comboBox_thrmcpltype.currentIndexChanged.connect(self.update_tempdevice)
        self.ui.comboBox_thrmcpltype.currentIndexChanged.connect(self.update_thrmcpltype)

        # set signals to update plots settings_settings
        self.ui.comboBox_timeunit.currentIndexChanged.connect(self.update_timeunit)
        self.ui.comboBox_timeunit.currentIndexChanged.connect(self.update_data_axis)
        self.ui.comboBox_timeunit.currentIndexChanged.connect(self.update_mpl_plt12)

        self.ui.comboBox_tempunit.currentIndexChanged.connect(self.update_tempunit)
        self.ui.comboBox_tempunit.currentIndexChanged.connect(self.update_data_axis)
        self.ui.comboBox_tempunit.currentIndexChanged.connect(self.update_mpl_plt12)

        self.ui.comboBox_xscale.currentIndexChanged.connect(self.update_timescale)
        self.ui.comboBox_xscale.currentIndexChanged.connect(self.update_data_axis)
        self.ui.comboBox_xscale.currentIndexChanged.connect(self.update_mpl_plt12)

        self.ui.comboBox_yscale.currentIndexChanged.connect(self.update_yscale)
        self.ui.comboBox_yscale.currentIndexChanged.connect(self.update_data_axis)
        self.ui.comboBox_yscale.currentIndexChanged.connect(self.update_mpl_plt12)

        self.ui.checkBox_linkx.stateChanged.connect(self.update_linkx)
        self.ui.checkBox_linkx.stateChanged.connect(self.update_data_axis)
        self.ui.checkBox_linkx.stateChanged.connect(self.update_mpl_plt12)
        
        #endregion


        #region settings_data

        # set treeWidget_settings_data_refs background
        self.ui.treeWidget_settings_data_refs.setStyleSheet(
            "QTreeWidget { background: transparent; }"
        )

        # load opts to combox
        for key, val in settings_init['ref_channel_opts'].items():
            # userData is setup for geting the plot type
            # userDat can be access with itemData(index)
            self.ui.comboBox_settings_data_samprefsource.addItem(val, key)
            self.ui.comboBox_settings_data_refrefsource.addItem(val, key)

        # move pushButton_settings_data_resetshiftedt0
        self.move_to_col2(
            self.ui.pushButton_settings_data_resetshiftedt0,
            self.ui.treeWidget_settings_data_refs,
            'Time Shift',
            100,
        )
        self.ui.pushButton_settings_data_resetshiftedt0.clicked.connect(self.reset_shiftedt0)

        # move label_settings_data_t0
        self.move_to_col2(
            self.ui.label_settings_data_t0,
            self.ui.treeWidget_settings_data_refs,
            't0',
            # 100,
        )

        # move dateTimeEdit_settings_data_t0shifted
        self.move_to_col2(
            self.ui.dateTimeEdit_settings_data_t0shifted,
            self.ui.treeWidget_settings_data_refs,
            'Shifted t0',
            # 180,
        )
        self.ui.dateTimeEdit_settings_data_t0shifted.dateTimeChanged.connect(self.on_dateTimeChanged_dateTimeEdit_t0shifted)

        # move frame_settings_data_recalcref
        self.move_to_col2(
            self.ui.frame_settings_data_recalcref,
            self.ui.treeWidget_settings_data_refs,
            'Reference',
            # 100,
        )
        self.ui.pushButton_settings_data_recalcref.clicked.connect(self.recalc_refs)

        # move frame_settings_data_sampref
        self.move_to_col2(
            self.ui.frame_settings_data_sampref,
            self.ui.treeWidget_settings_data_refs,
            'S chn.',
            # 100,
        )
        self.ui.comboBox_settings_data_samprefsource.currentIndexChanged.connect(self.update_widget)
        self.ui.lineEdit_settings_data_samprefidx.textChanged.connect(self.update_widget)

        # NOTE: following two only emitted when value manually edited (activated)
        self.ui.comboBox_settings_data_samprefsource.activated.connect(self.save_data_saver_sampref)
        self.ui.lineEdit_settings_data_samprefidx.textEdited.connect(self.save_data_saver_sampref)

        # move frame_settings_data_refref
        self.move_to_col2(
            self.ui.frame_settings_data_refref,
            self.ui.treeWidget_settings_data_refs,
            'R chn.',
            # 100,
        )
        self.ui.comboBox_settings_data_refrefsource.currentIndexChanged.connect(self.update_widget)
        self.ui.lineEdit_settings_data_refrefidx.textChanged.connect(self.update_widget)

        # NOTE: following two only emitted when value manually edited (activated)
        self.ui.comboBox_settings_data_refrefsource.activated.connect(self.save_data_saver_refref)
        self.ui.lineEdit_settings_data_refrefidx.textEdited.connect(self.save_data_saver_refref)

        
       # set treeWidget_settings_data_refs expanded
        self.ui.treeWidget_settings_data_refs.expandToDepth(0)

        #endregion 


        #region settings_mechanis
        ######### 
        self.ui.tabWidget_mechanics_chn.currentChanged.connect(self.update_mechanics_chn)

        for harm in range(1, settings_init['max_harmonic']+2, 2):
            getattr(self.ui, 'checkBox_nhplot' + str(harm)).toggled.connect(self.update_widget)

        self.ui.spinBox_settings_mechanics_nhcalc_n1.valueChanged.connect(self.update_widget)
        self.ui.spinBox_settings_mechanics_nhcalc_n2.valueChanged.connect(self.update_widget)
        self.ui.spinBox_settings_mechanics_nhcalc_n3.valueChanged.connect(self.update_widget)


        for harm in range(1, settings_init['max_harmonic']+2, 2): 
            # comboBox_settings_mechanics_refG
            self.ui.comboBox_settings_mechanics_refG.addItem('G'+str(harm), userData=str(harm))
        self.ui.comboBox_settings_mechanics_refG.currentIndexChanged.connect(self.update_widget)
        self.ui.comboBox_settings_mechanics_refG.currentIndexChanged.connect(self.update_qcm_rh)
        # set an initial value to active the key in self.settings
        self.ui.comboBox_settings_mechanics_refG.setCurrentIndex(0)

        self.ui.checkBox_settings_mechanics_witherror.toggled.connect(self.update_widget)

        # hide tableWidget_settings_mechanics_errortab
        self.ui.tableWidget_settings_mechanics_errortab.hide()
        # hide tableWidget_settings_mechanics_contoursettings
        self.ui.tableWidget_settings_mechanics_contoursettings.hide()
        # hide groupBox_settings_mechanics_simulator
        self.ui.groupBox_settings_mechanics_simulator.hide()

        for key, val in settings_init['qcm_model_opts'].items():
            self.ui.comboBox_settings_mechanics_selectmodel.addItem(val, userData=key)
        self.ui.comboBox_settings_mechanics_selectmodel.currentIndexChanged.connect(self.update_widget)

        #endregion


        #region spectra_show
        # add figure mpl_sp[n] into frame_sp[n]
        for i in range(1, settings_init['max_harmonic']+2, 2):
            # add first ax
            setattr(
                self.ui, 'mpl_sp' + str(i), 
                MatplotlibWidget(
                    parent=getattr(self.ui, 'frame_sp' + str(i)), 
                    axtype='sp',
                    showtoolbar=False,
                )
            )
            # getattr(self.ui, 'mpl_sp' + str(i)).fig.text(0.01, 0.98, str(i), va='top',ha='left') # option: weight='bold'
            getattr(self.ui, 'mpl_sp' + str(i)).update_sp_text_harm(str(i))
            # set mpl_sp<n> border
            getattr(self.ui, 'mpl_sp' + str(i)).setStyleSheet(
                "border: 0;"
            )
            getattr(self.ui, 'mpl_sp' + str(i)).setContentsMargins(0, 0, 0, 0)
            getattr(self.ui, 'frame_sp' + str(i)).setLayout(
                self.set_frame_layout(
                    getattr(self.ui, 'mpl_sp' + str(i))
                )
            )


        #endregion


        #region spectra_fit
        # add figure mpl_spectra_fit_polar into frame_spectra_fit_polar
        self.ui.mpl_spectra_fit_polar = MatplotlibWidget(
            parent=self.ui.frame_spectra_fit_polar, 
            axtype='sp_polar'
            )
        self.ui.frame_spectra_fit_polar.setLayout(self.set_frame_layout(self.ui.mpl_spectra_fit_polar))

        # add figure mpl_spectra_fit into frame_spactra_fit
        self.ui.mpl_spectra_fit = MatplotlibWidget(
            parent=self.ui.frame_spectra_fit, 
            axtype='sp_fit',
            showtoolbar=('Save',),
            # showtoolbar=False,
            ) 
        self.ui.frame_spectra_fit.setLayout(self.set_frame_layout(self.ui.mpl_spectra_fit))
        # connect signal
        self.ui.mpl_spectra_fit.ax[0].cidx = self.ui.mpl_spectra_fit.ax[0].callbacks.connect('xlim_changed', self.on_fit_lims_change)
        self.ui.mpl_spectra_fit.ax[0].cidy = self.ui.mpl_spectra_fit.ax[0].callbacks.connect('ylim_changed', self.on_fit_lims_change)
        
        # disconnect signal while dragging
        # self.ui.mpl_spectra_fit.canvas.mpl_connect('button_press_event', self.spectra_fit_axesevent_disconnect)
        # # reconnect signal after dragging (mouse release)
        # self.ui.mpl_spectra_fit.canvas.mpl_connect('button_release_event', self.spectra_fit_axesevent_connect)
            
        #
        self.ui.pushButton_manual_refit.clicked['bool'].connect(self.init_manual_refit)
        # hide widget for manual refit
        self.hide_widgets('manual_refit_enable_disable_list')


        self.ui.horizontalSlider_spectra_fit_spanctrl.valueChanged.connect(self.on_changed_slider_spanctrl)
        self.ui.horizontalSlider_spectra_fit_spanctrl.sliderReleased.connect(self.on_released_slider_spanctrl)
        self.ui.horizontalSlider_spectra_fit_spanctrl.actionTriggered .connect(self.on_acctiontriggered_slider_spanctrl)

        # pushButton_spectra_fit_refresh
        self.ui.pushButton_spectra_fit_refresh.clicked.connect(self.on_clicked_pushButton_spectra_fit_refresh)
        self.ui.pushButton_spectra_fit_showall.clicked.connect(self.on_clicked_pushButton_spectra_fit_showall)
        self.ui.pushButton_spectra_fit_fit.clicked.connect(self.on_clicked_pushButton_spectra_fit_fit)

        #endregion


        #region spectra_mechanics


        #endregion

        #region data
        # add mpl_legend into frame_legend
        self.ui.mpl_legend = MatplotlibWidget(
            parent=self.ui.frame_legend, 
            axtype='legend',
            showtoolbar=False,
            )
        self.ui.mpl_legend.setStyleSheet("background: transparent;")
        self.ui.frame_legend.setLayout(self.set_frame_layout(self.ui.mpl_legend))
        # change frame_legend height
        mpl_legend_p = self.ui.mpl_legend.leg.get_window_extent()
        self.ui.frame_legend.setFixedHeight((mpl_legend_p.p1[1]-mpl_legend_p.p0[1]))
        # self.ui.frame_legend.adjustSize()
        #endregion
        #region data_data

        # add figure mpl_plt1 into frame_spactra_fit
        self.ui.mpl_plt1 = MatplotlibWidget(
            parent=self.ui.frame_spectra_fit, 
            axtype='data',
            # ylabel=r'$\Delta f/n$ (Hz)',
            )
        self.ui.frame_plt1.setLayout(self.set_frame_layout(self.ui.mpl_plt1))


        # add figure mpl_plt2 into frame_spactra_fit
        self.ui.mpl_plt2 = MatplotlibWidget(
            parent=self.ui.frame_spectra_fit, 
            axtype='data',
            # ylabel=r'$\Delta \Gamma$ (Hz)',
            )
        self.ui.frame_plt2.setLayout(self.set_frame_layout(self.ui.mpl_plt2))

        # selector menu
        self.ui.mpl_plt1.canvas.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.mpl_plt1.canvas.customContextMenuRequested.connect(lambda position, mpl=self.ui.mpl_plt1, plt_str='plt1': self.mpl_data_open_custom_menu(position, mpl, plt_str))

        self.ui.mpl_plt2.canvas.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui.mpl_plt2.canvas.customContextMenuRequested.connect(lambda position, mpl=self.ui.mpl_plt2, plt_str='plt2': self.mpl_data_open_custom_menu(position, mpl, plt_str))

        self.ui.radioButton_data_showall.toggled['bool'].connect(self.update_widget)
        self.ui.radioButton_data_showall.clicked.connect(self.clr_mpl_l12)
        self.ui.radioButton_data_showall.clicked.connect(self.update_mpl_plt12)
        self.ui.radioButton_data_showmarked.toggled['bool'].connect(self.update_widget)
        self.ui.radioButton_data_showmarked.toggled['bool'].connect(self.set_mpl_lm_style) # when toggled clicked, this toggled too.
        self.ui.radioButton_data_showmarked.clicked.connect(self.clr_mpl_l12)
        self.ui.radioButton_data_showmarked.clicked.connect(self.update_mpl_plt12)

        # set signals to update plot 1 & 2 options
        for i in range(1, settings_init['max_harmonic']+2, 2):
            getattr(self.ui, 'checkBox_plt1_h' + str(i)).stateChanged.connect(self.update_widget)
            getattr(self.ui, 'checkBox_plt1_h' + str(i)).stateChanged.connect(self.update_mpl_plt1)
            getattr(self.ui, 'checkBox_plt1_h' + str(i)).stateChanged.connect(self.clr_mpl_harm)

            getattr(self.ui, 'checkBox_plt2_h' + str(i)).stateChanged.connect(self.update_widget)
            getattr(self.ui, 'checkBox_plt2_h' + str(i)).stateChanged.connect(self.update_mpl_plt2)
            getattr(self.ui, 'checkBox_plt2_h' + str(i)).stateChanged.connect(self.clr_mpl_harm)

        # set signals to update plot 1 options
        self.ui.comboBox_plt1_optsy.currentIndexChanged.connect(self.update_widget)
        self.ui.comboBox_plt1_optsy.currentIndexChanged.connect(self.update_data_axis)
        self.ui.comboBox_plt1_optsy.currentIndexChanged.connect(self.update_mpl_plt1)
        self.ui.comboBox_plt1_optsx.currentIndexChanged.connect(self.update_widget)
        self.ui.comboBox_plt1_optsx.currentIndexChanged.connect(self.update_data_axis)
        self.ui.comboBox_plt1_optsx.currentIndexChanged.connect(self.update_mpl_plt1)

        self.ui.radioButton_plt1_ref.toggled.connect(self.update_widget)
        self.ui.radioButton_plt1_ref.toggled.connect(self.ui.mpl_plt1.clr_all_lines)
        self.ui.radioButton_plt1_ref.clicked.connect(self.update_mpl_plt1)
        self.ui.radioButton_plt1_samp.toggled.connect(self.update_widget)
        self.ui.radioButton_plt1_samp.toggled.connect(self.ui.mpl_plt1.clr_all_lines)
        self.ui.radioButton_plt1_samp.clicked.connect(self.update_mpl_plt1)

        # set signals to update plot 2 options
        self.ui.comboBox_plt2_optsy.currentIndexChanged.connect(self.update_widget)
        self.ui.comboBox_plt2_optsy.currentIndexChanged.connect(self.update_data_axis)
        self.ui.comboBox_plt2_optsy.currentIndexChanged.connect(self.update_mpl_plt2)
        self.ui.comboBox_plt2_optsx.currentIndexChanged.connect(self.update_widget)
        self.ui.comboBox_plt2_optsx.currentIndexChanged.connect(self.update_data_axis)
        self.ui.comboBox_plt2_optsx.currentIndexChanged.connect(self.update_mpl_plt2)

        self.ui.radioButton_plt2_ref.toggled.connect(self.update_widget)
        self.ui.radioButton_plt2_ref.toggled.connect(self.ui.mpl_plt2.clr_all_lines)
        self.ui.radioButton_plt2_ref.clicked.connect(self.update_mpl_plt2)
        self.ui.radioButton_plt2_samp.toggled.connect(self.update_widget)
        self.ui.radioButton_plt2_samp.toggled.connect(self.ui.mpl_plt2.clr_all_lines)
        self.ui.radioButton_plt2_samp.clicked.connect(self.update_mpl_plt2)

        #endregion


        #region data_mechanics

        # add figure mpl_countour1 into frame_spectra_mechanics_contour1
        self.ui.mpl_countour1 = MatplotlibWidget(
            parent=self.ui.frame_spectra_mechanics_contour1, 
            axtype='contour'
            )
        self.ui.frame_spectra_mechanics_contour1.setLayout(self.set_frame_layout(self.ui.mpl_countour1))

        # add figure mpl_countour2 into frame_spectra_mechanics_contour2
        self.ui.mpl_countour2 = MatplotlibWidget(
            parent=self.ui.frame_spectra_mechanics_contour2, 
            axtype='contour',
            )
        self.ui.frame_spectra_mechanics_contour2.setLayout(self.set_frame_layout(self.ui.mpl_countour2))

        self.ui.pushButton_spectra_mechanics_clear.clicked.connect(self.del_prop_plot)
        #endregion


        #region status bar

        #### add widgets to status bar. from left to right
        # move progressBar_status_interval_time to statusbar
        self.ui.progressBar_status_interval_time.setAlignment(Qt.AlignCenter)
        self.ui.statusbar.addPermanentWidget(self.ui.progressBar_status_interval_time)
        # move label_status_pts to statusbar
        self.ui.statusbar.addPermanentWidget(self.ui.label_status_pts)
        # move pushButton_status_reftype to statusbar
        self.ui.statusbar.addPermanentWidget(self.ui.pushButton_status_reftype)
         # move pushButton_status_signal_ch to statusbar
        self.ui.statusbar.addPermanentWidget(self.ui.pushButton_status_signal_ch)
       # move pushButton_status_temp_sensor to statusbar
        self.ui.statusbar.addPermanentWidget(self.ui.pushButton_status_temp_sensor)
        # move label_status_f0BW to statusbar
        self.ui.statusbar.addPermanentWidget(self.ui.label_status_f0BW)

        #endregion


        #region action group

        # add menu to toolbutton

        # toolButton_settings_data_refit
        # create menu: menu_settings_data_refit
        self.ui.menu_settings_data_refit = QMenu(self.ui.toolButton_settings_data_refit)
        self.ui.menu_settings_data_refit.addAction(self.ui.actionFit_all)
        self.ui.menu_settings_data_refit.addAction(self.ui.actionFit_marked)
        # self.ui.menu_settings_data_refit.addAction(self.ui.actionFit_selected)
        # add menu to toolbutton
        self.ui.toolButton_settings_data_refit.setMenu(self.ui.menu_settings_data_refit)

        # toolButton_settings_mechanics_solve
        # create menu: menu_settings_mechanics_solve
        self.ui.menu_settings_mechanics_solve = QMenu(self.ui.toolButton_settings_mechanics_solve)
        self.ui.menu_settings_mechanics_solve.addAction(self.ui.actionSolve_all)
        self.ui.menu_settings_mechanics_solve.addAction(self.ui.actionSolve_marked)
        self.ui.actionSolve_all.triggered.connect(self.mech_solve_all)
        self.ui.actionSolve_marked.triggered.connect(self.mech_solve_marked)
        # add menu to toolbutton
        self.ui.toolButton_settings_mechanics_solve.setMenu(self.ui.menu_settings_mechanics_solve)

        # toolButton_spectra_mechanics_plotrows
        self.ui.actionRows_Time.triggered.connect(self.mechanics_plot_r_time)
        self.ui.actionRows_Temp.triggered.connect(self.mechanics_plot_r_temp)
        self.ui.actionRow_s1_Row_s2.triggered.connect(self.mechanics_plot_r1_r2)
        self.ui.actionRow_s2_Row_s1.triggered.connect(self.mechanics_plot_r2_r1)
        # create menu: menu_spectra_mechanics_plotrows
        self.ui.menu_spectra_mechanics_plotrows = QMenu(self.ui.toolButton_spectra_mechanics_plotrows)
        self.ui.menu_spectra_mechanics_plotrows.addAction(self.ui.actionRows_Time)
        self.ui.menu_spectra_mechanics_plotrows.addAction(self.ui.actionRows_Temp)
        self.ui.menu_spectra_mechanics_plotrows.addAction(self.ui.actionRow_s1_Row_s2)
        self.ui.menu_spectra_mechanics_plotrows.addAction(self.ui.actionRow_s2_Row_s1)
        # add menu to toolbutton
        self.ui.toolButton_spectra_mechanics_plotrows.setMenu(self.ui.menu_spectra_mechanics_plotrows)

        # # set action group channel
        # self.ui.group_channel = QActionGroup(self, exclusive=True)
        # self.ui.group_channel.addAction(self.ui.actionADC_1)
        # self.ui.group_channel.addAction(self.ui.actionADC_2)

        # # set action group refType
        # self.ui.group_refType = QActionGroup(self, exclusive=True)
        # self.ui.group_refType.addAction(self.ui.actionData_File)
        # self.ui.group_refType.addAction(self.ui.actionSingle_Point)
        # self.ui.group_refType.addAction(self.ui.actionExternal)

        # set QAction
        self.ui.actionLoad_Settings.triggered.connect(self.on_triggered_load_settings)
        self.ui.actionExport_Settings.triggered.connect(self.on_triggered_export_settings)
        self.ui.actionLoad_Exp.triggered.connect(self.on_triggered_load_exp)
        self.ui.actionNew_Exp.triggered.connect(self.on_triggered_new_exp)
        self.ui.actionSave.triggered.connect(self.on_triggered_actionSave)
        self.ui.actionSave_As.triggered.connect(self.on_triggered_actionSave_As)
        self.ui.actionExport.triggered.connect(self.on_triggered_actionExport)
        self.ui.actionReset.triggered.connect(self.on_triggered_actionReset)
        self.ui.actionClear_All.triggered.connect(self.on_triggered_actionClear_All)
        self.ui.actionOpen_MyVNA.triggered.connect(self.on_triggered_actionOpen_MyVNA)


        #endregion


        #region ###### add Matplotlib figures in to frames ##########

        # # create an empty figure and move its toolbar to TopToolBarArea of main window
        # self.ui.mpl_dummy_fig = MatplotlibWidget()
        # self.addToolBar(Qt.TopToolBarArea, self.ui.mpl_dummy_fig.toolbar)
        # self.ui.mpl_dummy_fig.hide() # hide the figure

        



        #endregion


        #endregion

        #region ###### set UI value ###############################

        # for i in range(1, settings_init['max_harmonic']+2, 2):
        #     if i in self.settings['harmonics_check']: # in the default range 
        #         # settings/control/Harmonics
        #         getattr(self.ui, 'checkBox_harm' + str(i)).setChecked(True)
        #         getattr(self.ui, 'checkBox_tree_harm' + str(i)).setChecked(True)

        #     else: # out of the default range
        #         getattr(self.ui, 'checkBox_harm' + str(i)).setChecked(False)
        #         getattr(self.ui, 'checkBox_tree_harm' + str(i)).setChecked(False)
        #         # hide spectra/sp
        #         getattr(self.ui, 'frame_sp' + str(i)).setVisible(False)


        # self.ui.comboBox_plt1_optsy.setCurrentIndex(2)
        # self.ui.comboBox_plt2_optsy.setCurrentIndex(3)

        # set time interval
        # self.ui.lineEdit_scaninterval.setText(str(self.settings['lineEdit_scaninterval']))
        # self.ui.lineEdit_recordinterval.setText(str(self.settings['lineEdit_recordinterval']))
        # self.ui.lineEdit_refreshresolution.setText(str(self.settings['lineEdit_refreshresolution']))

        #endregion


        #region #########  functions ##############

    def link_tab_page(self, tab_idx):
        self.UITab = tab_idx
        if tab_idx in [0, 2]: # link settings_control to spectra_show and data_data
            self.ui.stackedWidget_spectra.setCurrentIndex(0)
            self.ui.stackedWidget_data.setCurrentIndex(0)
        elif tab_idx in [1]: # link settings_settings and settings_data to spectra_fit 
            self.ui.stackedWidget_spectra.setCurrentIndex(1)
            self.ui.stackedWidget_data.setCurrentIndex(0)
        elif tab_idx in [3]: # link settings_mechanics to spectra_mechanics and data_mechanics
            self.ui.stackedWidget_spectra.setCurrentIndex(2)
            self.ui.stackedWidget_data.setCurrentIndex(1)

    def create_combobox(self, name, contents, box_width, row_text='', parent=''):
        ''' 
        this function create a combobox object with its name = name, items = contents. and  set it't width. 
        And move it to row[0] = row_text in parent
        '''
        # create a combobox object
        setattr(self.ui, name, QComboBox())
        # get the object
        obj_box = getattr(self.ui, name)
        # set objectName
        obj_box.setObjectName(name)
        # set its size adjust policy
        obj_box.SizeAdjustPolicy(QComboBox.AdjustToContents)
        # add items from contents
        if isinstance(contents, list): # if given a list, add only the text
            for val in contents:
                obj_box.addItem(val)
        elif isinstance(contents, dict): # if given a dict, add the text (val) and userData (key)
            for key, val in contents.items():
                obj_box.addItem(val, key)

        # insert to the row of row_text if row_text and parent_name are not empty
        if (row_text and parent):
            self.move_to_col2(obj_box, parent, row_text, box_width)
            

    def move_to_col2(self, obj, parent, row_text, width=[]): 
        if width: # set width of obj
            obj.setMaximumWidth(width)
        # find item with row_text
        item = self.find_text_item(parent, row_text)
        # insert the combobox in to the 2nd column of row_text
        parent.setItemWidget(item, 1, obj)        

    def find_text_item(self, parent, text):
        '''
        find item with 'text' in widgets e.g.: treeWidget, tableWidget
        return a item
        Make sure the text is unique in the widget
        if not, return None
        '''
        item = parent.findItems(text, Qt.MatchExactly | Qt.MatchRecursive, 0)
        if len(item) == 1:
            item = item[0]
        else:
            item = None
        return item
        

    def set_frame_layout(self, widget):
        '''set a dense layout for frame with a single widget'''
        vbox = QGridLayout()
        vbox.setContentsMargins(0, 0, 0, 0) # set layout margins (left, top, right, bottom)
        vbox.addWidget(widget)
        return vbox


    ########## action functions ##############
    # @pyqtSlot['bool']
    def on_clicked_pushButton_runstop(self, checked):
        if checked:
            # turn off manual refit mode
            self.ui.pushButton_manual_refit.setChecked(False)

            # check checked harmonice if no, stop
            harm_list = self.get_all_checked_harms()
            if not harm_list:
                self.ui.pushButton_runstop.setChecked(False)
                # TODO update statusbar
                return
            # check filename if avaialbe
            if not self.data_saver.path: # no filename
                if self.tempPath: # new file name is set
                    path = self.tempPath
                else: # no file name is set. save data to a temp file
                    path=os.path.join(settings_init['unsaved_path'], datetime.datetime.now().strftime('%Y%m%d%H%M%S') + '.h5')
                self.data_saver.init_file(
                    path=path,
                    settings=self.settings,
                    t0=self.settings['dateTimeEdit_reftime']
                ) # save to unsaved folder
                # update exp_ref in UI
                self.load_refsource()
                self.update_refsource()

            # disable features
            self.disable_widgets(
                'pushButton_runstop_disable_list'
            )

            # cmd diary?

            # test scheduler? start/end increasement

            # start the timer
            self.timer.start(0)


            self.ui.pushButton_runstop.setText('STOP')
        else:
            # set text on button for waitiong
            self.ui.pushButton_runstop.setText('FINISHING...')
            # stop running timer and/or test
            # print(self.timer.isActive())
            self.timer.stop()
            # print(self.timer.isActive())

            # stop bartimer
            self.bartimer.stop()
            # reset progressbar
            self.updat_progressbar(val=0, text='')

            # # wait for data_collection fun finish (self.idle == True)
            # while self.idle == False:
            #     loop = QEventLoop()
            #     QTimer.singleShot(1000, loop.quit)
            #     loop.exec_()
            #     print('looping')

            # write dfs and settings to file
            if self.idle == True: # Timer stopped while timeout func is not running
                self.process_saving_when_stop()



    def process_saving_when_stop(self):
        '''
        process saving fitted data when tested is stopped
        '''
        # save data
        self.data_saver.save_data()
        # write UI information to file
        self.data_saver.save_data_settings(settings=self.settings) # TODO add exp_ref

        self.counter = 0 # reset counter

        print('data saver samp')
        print(self.data_saver.samp)

        # enable features
        self.enable_widgets(
            'pushButton_runstop_enable_list'
        )

        # 
        self.ui.pushButton_runstop.setText('START RECORD')   

    # @pyqtSlot()
    def reset_reftime(self):
        ''' 
        set time in dateTimeEdit_reftime 
        '''
        # use qt use python deal with datetime. But show the time with QdatetimeEdit
        self.ui.dateTimeEdit_reftime.setDateTime(datetime.datetime.now())
    
    def on_dateTimeChanged_dateTimeEdit_reftime(self, datetime):
        '''
        get time in dateTimeEdit_reftime and save it to self.settings
        '''
        self.settings['dateTimeEdit_reftime'] = self.ui.dateTimeEdit_reftime.dateTime().toPyDateTime().strftime(settings_init['time_str_format'])
        print(self.settings['dateTimeEdit_reftime'])
        self.ui.label_settings_data_t0.setText(self.settings['dateTimeEdit_reftime'][:-3]) # [:-3] remove the extra 000 at the end
        self.data_saver.set_t0(t0=self.settings['dateTimeEdit_reftime'])

    def on_dateTimeChanged_dateTimeEdit_t0shifted(self, datetime):
        '''
        get time in dateTimeEdit_settings_data_t0shifted 
        and save it to self.settings and data_saver
        '''
        self.settings['dateTimeEdit_settings_data_t0shifted'] = self.ui.dateTimeEdit_settings_data_t0shifted.dateTime().toPyDateTime().strftime(settings_init['time_str_format'])
        print(self.settings['dateTimeEdit_settings_data_t0shifted'])
        
        self.data_saver.set_t0(t0_shifted=self.settings['dateTimeEdit_settings_data_t0shifted'])

    def reset_shiftedt0(self):
        '''
        reset shiftedt0 to t0
        '''
        self.ui.dateTimeEdit_settings_data_t0shifted.setDateTime(datetime.datetime.strptime(self.settings['dateTimeEdit_reftime'], settings_init['time_str_format']))

    def save_data_saver_sampref(self):
        '''
        set the data_saver.exp_ref['samp_ref']
        '''
        self.save_data_saver_refsource('samp')
        

    def save_data_saver_refref(self):
        '''
        set the data_saver.exp_ref['ref_ref']
        '''
        self.save_data_saver_refsource('ref')

    def save_data_saver_refsource(self, chn_name):
        '''
        set the data_saver.exp_ref[chn_name]
        '''
        print('save_data_saver_refsource')
        print('chn_name', chn_name)
        ref_source = self.settings['comboBox_settings_data_'+ chn_name + 'refsource']
        ref_idx = self.settings['lineEdit_settings_data_'+ chn_name + 'refidx']
        print('ref_source', ref_source)
        print('ref_idx', ref_idx, type(ref_idx))

        chn_queue_list = list(self.data_saver.get_queue_id(ref_source).tolist()) # list of available index in the target chn
        # convert ref_idx from str to a list of int
        ref_idx = UIModules.index_from_str(ref_idx, chn_queue_list)
        print('ref_idx', ref_idx, type(ref_idx))
        # if the list is [] set it to [0], which mean the first data of the channel
        if (not ref_idx) and (list(self.data_saver.get_queue_id('samp')) !=  list(self.data_saver.get_queue_id('ref'))): # samp and ref were not collected together
            ref_idx = [0]
            getattr(self.ui, 'lineEdit_settings_data_'+ chn_name + 'refidx').setText('[0]') 
            self.settings['lineEdit_settings_data_'+ chn_name + 'refidx'] = '[0]' 

        # # save to data_saver
        # self.data_saver.exp_ref[chn_name + '_ref'][0] = ref_source
        # self.data_saver.exp_ref[chn_name + '_ref'][1] = ref_idx

        # save to data_saver and
        # update and set reference
        self.data_saver.set_ref_set(chn_name, ref_source, ref_idx, df=None) # TODO add df if ref_source == exp

        # refresh mpl_plt<n>
        self.update_mpl_plt12()

    def recalc_refs(self):
        '''
        recalculate delf and delg by reference set saved in data_saver
        '''
        self.data_saver.calc_fg_ref('samp', mark=True)
        self.data_saver.calc_fg_ref('ref', mark=True)

    def on_triggered_actionOpen_MyVNA(self):
        '''
        open myVNA
        '''
        subprocess.Popen(settings_init['vna_path'])






    # @pyqtSlot()
    def set_lineEdit_scaninterval(self):
        # get text
        record_interval = self.ui.lineEdit_recordinterval.text()
        refresh_resolution = self.ui.lineEdit_refreshresolution.text()
        #convert to flot
        try:
            record_interval = float(record_interval)
            if record_interval <= 0: # illegal value
                raise ZeroDivisionError
        except:
            record_interval = self.settings['lineEdit_recordinterval']
            self.ui.lineEdit_recordinterval.setText(str(record_interval))
            self.settings['lineEdit_recordinterval'] = record_interval
        try:
            refresh_resolution = float(refresh_resolution)
            if refresh_resolution <= 0: # illegal value
                raise ZeroDivisionError
        except:
            refresh_resolution = settings_init['lineEdit_refreshresolution']
            self.ui.lineEdit_refreshresolution.setText(refresh_resolution)
            self.settings['lineEdit_refreshresolution'] = refresh_resolution
            
        # set lineEdit_scaninterval
        # self.ui.lineEdit_scaninterval.setText(f'{record_interval * refresh_resolution}  s')
        self.settings['lineEdit_recordinterval'] = float(record_interval)
        self.settings['lineEdit_refreshresolution'] = float(refresh_resolution)
        try:
            self.settings['lineEdit_scaninterval'] = record_interval / refresh_resolution
            self.ui.lineEdit_scaninterval.setText('{0:.3g}'.format(record_interval / refresh_resolution)) # python < 3.5
        except ZeroDivisionError:
            self.settings['lineEdit_scaninterval'] = 1
            self.ui.lineEdit_scaninterval.setText('{0:.3g}'.format(math.inf)) # python < 3.5

    ## functions for open and save file
    def openFileNameDialog(self, title, path='', filetype=settings_init['default_datafiletype']):  
        options = QFileDialog.Options()
        # options |= QFileDialog.DontUseNativeDialog
        fileName, _ = QFileDialog.getOpenFileName(self, title, path, filetype, options=options)
        if fileName:
            print(type(fileName))
        else:
            fileName = ''
        return fileName
        
    # def openFileNamesDialog(self, title, path=''):    
    #     options = QFileDialog.Options()
    #     options |= QFileDialog.DontUseNativeDialog
    #     files, _ = QFileDialog.getOpenFileNames(self,title, "","All Files (*);;Python Files (*.py)", options=options)
    #     if files:
    #         print(files)
 
    def saveFileDialog(self, title, path='', filetype=settings_init['default_datafiletype']):    
        options = QFileDialog.Options()
        # options |= QFileDialog.DontUseNativeDialog
        fileName, _ = QFileDialog.getSaveFileName(self,title, path, filetype, options=options)
        if fileName:
            print(fileName)
        else:
            fileName = ''
        return fileName 

    def on_triggered_new_exp(self):
        process = self.process_messagebox(message='Create a new experiment!')

        if not process: 
            return

        fileName = self.saveFileDialog(title='Choose a new file') # !! add path of last opened folder
        if fileName:
            # change the displayed file directory in lineEdit_datafilestr
            self.ui.lineEdit_datafilestr.setText(fileName)
            self.tempPath = fileName # 
            # reset dateTimeEdit_reftime
            self.reset_reftime()
            # set enable
            self.enable_widgets(
                'pushButton_newfile_enable_list',
            )

            # t0 = time.time()

            # leave the init_file when click start button
            # self.data_saver.init_file(path=fileName, settings_init=settings_init, t0=self.settings['dateTimeEdit_reftime']) 

            # t1 = time.time()
            # print(t1 -t0)

    def on_triggered_load_exp(self): 

        process = self.process_messagebox(message='Load new experiment data!')

        if not process: 
            return

        fileName = self.openFileNameDialog(title='Choose an existing file to append') # !! add path of last opened folder
        if fileName:
            # load UI settings
            self.data_saver.load_file(fileName) # load factors from file to data_saver
            self.on_triggered_actionReset(settings=self.data_saver.settings)
            
            self.disable_widgets(
                'pushButton_appendfile_disable_list',
            )

            # change the displayed file directory in lineEdit_datafilestr and save it to data_saver
            self.set_filename(fileName)

    # open folder in explorer
    # methods for different OS could be added
    def on_clicked_pushButton_gotofolder(self):
        file_path = self.ui.lineEdit_datafilestr.text() #TODO replace with reading from settings dict
        path = os.path.abspath(os.path.join(file_path, os.pardir)) # get the folder of the file
        UIModules.open_file(path)

    # 
    def on_triggered_load_settings(self):

        process = self.process_messagebox(message='Load settings from other file!')

        if not process: 
            return

        fileName = self.openFileNameDialog('Choose a file to load its settings', path=self.data_saver.path, filetype=settings_init['default_settings_load_filetype']) # TODO add path of last opened folder

        if fileName: 

            # load settings from file
            name, ext = os.path.splitext(fileName)
            if ext == '.h5': 
                settings = self.data_saver.load_settings(path=fileName)
            elif ext == '.json':
                with open(fileName, 'r') as f:
                    settings = json.load(f)
            else:
                settings = None
            # reset default settings
            # replase keys in self.settings with those in settings_default
            if not settings:
                print('File with wrong fromat!')
                return
            else:
                for key, val in settings.items():
                    self.settings[key] = val

            # reload widgets' setup 
            self.load_settings()

    def on_triggered_export_settings(self):
        process = self.process_messagebox(message='Export settings to a file!')
        if not process: 
            return

        fileName = self.saveFileDialog('Choose a file to load its settings', path=self.data_saver.path, filetype=settings_init['default_settings_export_filetype']) # TODO add path of last opened folder

        if fileName: 
            # load settings from file
            name, ext = os.path.splitext(fileName)
            if ext == '.json':
                with open(fileName, 'w') as f:
                    settings = self.settings.copy()
                    settings.pop('dateTimeEdit_reftime', None)
                    line = json.dumps(settings, indent=4) + "\n"
                    f.write(line)
                print('Settings were exported as json file.')
                #TODO statusbar

    def on_triggered_actionSave(self):
        '''
        save current data to file if file has been opened
        '''
        # turn off manual refit mode
        self.ui.pushButton_manual_refit.setChecked(False)

        if self.data_saver.path: # there is file 
            self.data_saver.save_data_settings(settings=self.settings)
            print('Data has been saved to file!')
        elif not self.data_saver.path & self.tempPath: # name given but file not been created (no data)
            print('No data collected!')
        else:
            print('No file information!')


    def on_triggered_actionSave_As(self):
        ''' save current data to a new file  '''

        # turn off manual refit mode
        self.ui.pushButton_manual_refit.setChecked(False)

        # export data to a selected form
        fileName = self.saveFileDialog(title='Choose a new file', filetype=settings_init['default_datafiletype'], path=self.data_saver.path) # !! add path of last opened folder
        # codes for data exporting
        if fileName:
            if self.data_saver.path: # there is file 

                # copy file
                try:
                    shutil.copyfile(self.data_saver.path, fileName)
                except Exception as e:
                    print('Failed to copy file!')
                    print(e)
                    return
                # change the path in data_saver
                self.data_saver.path = fileName
                # save modification to new file
                self.data_saver.save_data_settings() 


    def on_triggered_actionExport(self):
        ''' export data to a selected format '''
        process = self.process_messagebox(message='Export data to a selected format!')
        if not process: 
            return

        fileName = self.saveFileDialog(title='Choose a file and data type', filetype=settings_init['export_datafiletype'], path=self.data_saver.path) # !! add path of last opened folder
        # codes for data exporting
        if fileName:
            self.data_saver_data_exporter(fileName) # do the export

    def process_messagebox(self, message=[]):
        '''
        check is the experiment is ongoing (self.timer.isActive()) and if data is saved (self.data_saver.saveflg)
        and pop up a messageBox to ask if process

        return process: Ture/False for checking
        '''

        process = True

        if self.timer.isActive() or self.data_saver.saveflg == False:
            if self.data_saver.saveflg == False:
                message.append('There is data unsaved!')
            if self.timer.isActive():
                message.append('Test is Running!')
                buttons = QMessageBox.Ok
            else:
                message.append('Do you want to process?')
                buttons = QMessageBox.Yes | QMessageBox.Cancel

            msg = QMessageBox()
            msg.setIcon(QMessageBox.Information)
            msg.setText('Your selection was paused!')
            msg.setInformativeText('\n'.join(message))
            msg.setWindowTitle(_version.__projectname__ + ' Message')
            msg.setStandardButtons(buttons)
            retval = msg.exec_()

            if retval == QMessageBox.Yes:
                if self.timer.isActive():
                    # stop test
                    self.ui.pushButton_runstop.setChecked(False)
                
                process = True

        if process:
            # turn off manual refit mode
            self.ui.pushButton_manual_refit.setChecked(False)


        return process
           

    def on_triggered_actionReset(self, settings=None):
        """ 
        reset MainWindow 
        if settings is given, it will load the given settings (load settings)
        """

        process = self.process_messagebox()

        if not process: 
            return

        # clear all mpl objects
        self.clear_all_mpl()

        # set widgets enabled by using the disabled list
        self.enable_widgets(
            'pushButton_runstop_disable_list',
            'pushButton_appendfile_disable_list',
        )

        # reset default settings
        # replase keys in self.settings with those in settings_default
        if not settings:
            for key, val in settings_default.items():
                self.settings[key] = val
        else:
            for key, val in settings.items():
                self.settings[key] = val
        self.peak_tracker = PeakTracker.PeakTracker()
        self.vna_tracker = VNATracker()

        # reload widgets' setup 
        self.load_settings()

        if not settings: # reset UI
            self.data_saver = DataSaver.DataSaver(ver=_version.__version__, settings_init=settings_init)
            # enable widgets
            self.enable_widgets(
                'pushButton_runstop_disable_list',
                'pushButton_appendfile_disable_list',
            )
        # clear fileName
        self.set_filename()

        # reset  status pts
        self.set_status_pts()

    def on_triggered_actionClear_All(self):
        '''
        clear all data
        ''' 
        if not self.data_saver.path: # no data 
            return

        process = self.process_messagebox(message='All data will be deleted!')

        if not process: 
            return

        print(self.data_saver.path)
        # re-initiate file
        self.data_saver.init_file(self.data_saver.path, settings=self.settings, t0=self.settings['dateTimeEdit_reftime']) 
        # enable widgets
        self.enable_widgets(
            'pushButton_runstop_disable_list',
            'pushButton_appendfile_disable_list',
        )

        # clear all mpl objects
        self.clear_all_mpl()

    def clear_all_mpl(self):
        '''
        clear lines in all mpls
        '''
        # find all mpl objects
        mpl_list = self.findChildren(MatplotlibWidget)
        print(mpl_list)
        # clear mpl_sp
        for mpl in mpl_list:
            mpl.clr_lines()

    
    def set_status_pts(self):
        '''
        set status bar label_status_pts
        '''
        # self.ui.label_status_pts.setText(str(self.data_saver.get_npts()))
        print(str(self.data_saver.get_npts()))
        try:
            # print(10)
            self.ui.label_status_pts.setText(str(self.data_saver.get_npts()))
            # print(11)
        except:
            # print(21)
            self.ui.label_status_pts.setText('pts')
            # print(22)

    def show_widgets(self, *args):
        '''
        show widgets in given args
        args: list of names
        '''
        print('show')
        print(args)
        for name_list in args:
            for name in settings_init[name_list]:
                print(name)
                if name not in settings_init['version_hide_list'] or name_list == 'version_hide_list': 
                    # getattr(self.ui, name).show()
                    getattr(self.ui, name).setVisible(True)

    def hide_widgets(self, *args):
        '''
        hide widgets in given args
        args: list of names
        '''
        print('hide')
        print(args)
        for name_list in args:
            for name in settings_init[name_list]:
                print(name)
                if name not in settings_init['version_hide_list'] or name_list == 'version_hide_list': 
                    # getattr(self.ui, name).hide()
                    getattr(self.ui, name).setVisible(False)


    def enable_widgets(self, *args):
        '''
        enable/ widgets in given args
        args: list of names
        '''
        print(args)
        for name_list in args:
            for name in settings_init[name_list]:
                if name not in settings_init['version_hide_list'] or name_list == 'version_hide_list': 
                    getattr(self.ui, name).setEnabled(True)

    def disable_widgets(self, *args):
        '''
        disable widgets in given args
        args: list of names
        '''
        print(args)
        for name_list in args:
            for name in settings_init[name_list]:
                if name not in settings_init['version_hide_list'] or name_list == 'version_hide_list': 
                    getattr(self.ui, name).setEnabled(False)

    def set_filename(self, fileName=''):
        '''
        set self.data_saver.path and lineEdit_datafilestr
        '''
        self.data_saver.path = fileName
        self.ui.lineEdit_datafilestr.setText(fileName)

    def on_acctiontriggered_slider_spanctrl(self, value):
        '''
        disable the actions other than mouse dragging
        '''
        # print(value)
        if value < 7: # mous dragging == 7
            # reset slider to 1
            self.ui.horizontalSlider_spectra_fit_spanctrl.setValue(0)

    def on_changed_slider_spanctrl(self):
        # get slider value
        n = 10 ** (self.ui.horizontalSlider_spectra_fit_spanctrl.value() / 10)
        # format n
        if n >= 1:
            # n = f'{round(n)} *'
            n = '{} *'.format(min(settings_init['span_ctrl_steps'], key=lambda x:abs(x-n))) # python < 3.5
        else:
            # n = f'1/{round(1/n)} *'
            n = '1/{} *'.format(min(settings_init['span_ctrl_steps'], key=lambda x:abs(x-1/n))) # python < 3.5
        # set label_spectra_fit_zoomtimes value
        self.ui.label_spectra_fit_zoomtimes.setText(str(n))

    def on_released_slider_spanctrl(self):

        # get slider value
        n = 10 ** (self.ui.horizontalSlider_spectra_fit_spanctrl.value() / 10)
        # format n
        if n >= 1:
            n = min(settings_init['span_ctrl_steps'], key=lambda x:abs(x-n))
        else:
            n = 1/min(settings_init['span_ctrl_steps'], key=lambda x:abs(x-1/n))

        # get f1, f2
        # f1, f2 = self.ui.mpl_spectra_fit.ax[0].get_xlim()
        f1, f2 = self.get_freq_span()
        # convert start/end (f1/f2) to center/span (fc/fs)
        fc, fs = UIModules.converter_startstop_to_centerspan(f1, f2)
        # multiply fs
        fs = fs * n
        # fc/fs back to f1/f2
        f1, f2 = UIModules.converter_centerspan_to_startstop(fc, fs)

        # set lineEdit_scan_harmstart & lineEdit_scan_harmend
        self.ui.lineEdit_scan_harmstart.setText(str(f1*1e-6)) # in MHz
        self.ui.lineEdit_scan_harmend.setText(str(f2*1e-6)) # in MHz

        # reset xlim to active on_fit_lims_change
        self.ui.mpl_spectra_fit.ax[0].set_xlim(f1, f2)

        # # update limit of active harmonic
        # self.on_editingfinished_harm_freq()
        
        # # get new data
        # f, G, B = self.spectra_fit_get_data()
        
        # # plot
        # self.tab_spectra_fit_update_mpls(f, G, B)

        # reset slider to 1
        self.ui.horizontalSlider_spectra_fit_spanctrl.setValue(0)


    def span_check(self, harm=None, f1=None, f2=None):
        '''
        check if lower limit ('f1' in Hz) and upper limit ('f2' in Hz) in base freq +/- BW of harmonic 'harm'
        if out of the limit, return the part in the range
        and show alert in statusbar
        '''
        if harm is None:
            harm = self.settings_harm
        # get freq_range
        bf1, bf2 = self.settings['freq_range'][harm] # in Hz
        # check f1, and f2
        if f1 and (f1 < bf1 or f1 >= bf2): # f1 out of limt
            f1 = bf1
            #TODO update statusbar 'lower bound out of limit and reseted. (You can increase the bandwidth in settings)'
        if f2 and (f2 > bf2 or f2 <= bf1): # f2 out of limt
            f2 = bf2
            #TODO update statusbar 'upper bond out of limit and reseted. (You can increase the bandwidth in settings)'
        if f1 and f2 and (f1 >= f2):
            f2 = bf2

        return [f1, f2]

    def get_spectraTab_mode(self):
        '''
        get the current UI condition from attributes and 
        set the mode for spectra_fit
        '''
        mode = None   # None/center/refit
      
        if self.idle == True: # no test is running
            if self.UITab == 1: # setting
                mode = 'center'
            elif self.UITab == 2: # Data
                mode = 'refit'
            else:
                mode = None
        else: # test is running
            if self.reading == True: # vna and/or temperature sensor is reading data
                if self.UITab == 2: # Data
                    mode  = 'refit'
                else:
                    mode  = None
            else: # is waiting for next reading
                if self.UITab == 1: # setting
                    mode = 'center'
                elif self.UITab == 2: # Data
                    mode = 'refit'
                else:
                    mode = None
        
        if self.ui.tabWidget_settings_settings_samprefchn.currentIndex() > 1:
            mode = 'refit'
        return mode

    def spectra_fit_get_data(self):
        ''' 
        get data for mpl_spectra_fit by spectraTab_mode and 
        return f, G, B
        '''
        f = None
        G = None
        B = None
        if self.get_spectraTab_mode() == 'center': # for peak centering
            # get harmonic from self.settings_harm
            harm = self.settings_harm
            chn = self.settings_chn['chn']
            print(type(chn))
            chn_name = self.settings_chn['name']

            with self.vna: # use get_vna_data_no_with which doesn't have with statement and could keep the vna attributes
                f, G, B = self.get_vna_data_no_with(harm=harm, chn_name=chn_name)

        elif self.get_spectraTab_mode() == 'refit': # for refitting
            # get 

            # get raw of active queue_id from data_saver
            f, G, B = self.get_active_raw()
                    # get the vna reset flag
            freq_span = self.get_freq_span(harm=self.active['harm'], chn_name=self.active['chn_name'])

            idx = np.where((f >= freq_span[0]) & (f <= freq_span[1]))
            f, G, B = f[idx], G[idx], B[idx]
        else:
            print('Change Tab to Settings or Data to active the function.')
        
        return f, G, B

    def get_vna_data(self, harm=None, chn_name=None):
        ''' 
        get data from vna use given channel(int) and harmonic (int)
        return f, G, B
        '''
        f = None
        G = None
        B = None

        if harm is None:
            harm = self.settings_harm
        if chn_name is None:
            chn_name = self.settings_chn['name']

        # get the vna reset flag
        freq_span = self.get_freq_span(harm=harm, chn_name=chn_name)
        steps = int(self.get_harmdata('lineEdit_scan_harmsteps', harm=harm, chn_name=chn_name))
        setflg = self.vna_tracker.set_check(f=freq_span, steps=steps, chn=self.get_chn_by_name(chn_name))
        print(setflg)

        print(vna)
        with self.vna:
            print(vna)
            print('vna._naverage', self.vna._naverage)
            ret = self.vna.set_vna(setflg)
            if ret == 0:
                ret, f, G, B = self.vna.single_scan()
                return f, G, B
            else:
                print('There is an error while setting VNA!')
        return f, G, B

    def get_vna_data_no_with(self, harm=None, chn_name=None):
        ''' 
        NOTE: no with condition used. It can be used for 
        continous reading data from different harms and chns.
        You need to add with condition out of it by yourself.

        get data from vna use given channel(int) and harmonic (int)
        return f, G, B
        '''
        f = None
        G = None
        B = None

        if harm is None:
            harm = self.settings_harm
        if chn_name is None:
            chn_name = self.settings_chn['name']

        # get the vna reset flag
        freq_span = self.get_freq_span(harm=harm, chn_name=chn_name)
        steps = int(self.get_harmdata('lineEdit_scan_harmsteps', harm=harm, chn_name=chn_name))
        setflg = self.vna_tracker.set_check(f=freq_span, steps=steps, chn=self.get_chn_by_name(chn_name))
        print(setflg)
        ret = self.vna.set_vna(setflg)
        if ret == 0:
            ret, f, G, B = vna.single_scan()
        else:
            print('There is an error while setting VNA!')
        return f, G, B

    def tab_spectra_fit_update_mpls(self, f, G, B):
        ''' update mpl_spectra_fit and mpl_spectra_fit_polar '''
        ## disconnect axes event
        self.mpl_disconnect_cid(self.ui.mpl_spectra_fit) 
               
        self.ui.mpl_spectra_fit.update_data(('lG', f, G))
        self.ui.mpl_spectra_fit.update_data(('lB', f, B))

        # constrain xlim
        self.ui.mpl_spectra_fit.ax[0].set_xlim(f[0], f[-1])
        self.ui.mpl_spectra_fit.ax[1].set_xlim(f[0], f[-1])
        self.ui.mpl_spectra_fit.ax[0].set_ylim(min(G)-0.05*(max(G)-min(G)), max(G)+0.05*(max(G)-min(G)))
        self.ui.mpl_spectra_fit.ax[1].set_ylim(min(B)-0.05*(max(B)-min(B)), max(B)+0.05*(max(B)-min(B)))

        ## connect axes event
        self.mpl_connect_cid(self.ui.mpl_spectra_fit, self.on_fit_lims_change)

        self.ui.mpl_spectra_fit.canvas.draw()

        self.ui.mpl_spectra_fit_polar.update_data(('l', G, B))
        
        # set xlabel
        # self.mpl_set_faxis(self.ui.mpl_spectra_fit.ax[0])

        # update lineedit_fit_span
        self.update_lineedit_fit_span(f)


    def on_clicked_pushButton_spectra_fit_refresh(self):
        print('vna', self.vna)
        # get data
        f, G, B = self.spectra_fit_get_data()

        # update raw
        self.tab_spectra_fit_update_mpls(f, G, B)


    def on_clicked_pushButton_spectra_fit_showall(self):
        ''' show whole range of current harmonic'''
        if self.get_spectraTab_mode() == 'center': # for peak centering
            # get harmonic
            harm = self.settings_harm
            # set freq_span[harm] to the maximum range (freq_range[harm])
            self.set_freq_span(self.settings['freq_range'][harm])

        elif self.get_spectraTab_mode() == 'refit': # for peak refitting
            # get raw of active queue_id from data_saver
            f, _, _ = self.get_active_raw()
            self.set_freq_span([f[0], f[-1]])

        ## reset xlim to active on_fit_lims_change, emit scan and updating harmtree
        self.ui.mpl_spectra_fit.ax[0].set_xlim(self.get_freq_span())

    def on_fit_lims_change(self, axes):
        print('on lim changed')
        axG = self.ui.mpl_spectra_fit.ax[0]

        # print('g', axG.get_contains())
        # print('r', axG.contains('button_release_event'))
        # print('p', axG.contains('button_press_event'))

        # data lims [min, max]
        # df1, df2 = UIModules.datarange(self.ui.mpl_spectra_fit.l['lB'][0].get_xdata())
        # get axes lims
        f1, f2 = axG.get_xlim()
        # check lim with BW
        f1, f2 = self.span_check(harm=self.settings_harm, f1=f1, f2=f2)
        print('get_navigate_mode()', axG.get_navigate_mode())
        print('flims', f1, f2)
        # print(df1, df2)
        
        print(axG.get_navigate_mode())
        # if axG.get_navigate_mode() == 'PAN': # pan
        #     # set a new x range: combine span of dflims and flims
        #     f1 = min([f1, df1])
        #     f2 = max([f2, df2])
        # elif axG.get_navigate_mode() == 'ZOOM': # zoom
        #     pass
        # else: # axG.get_navigate_mode() == 'None'
        #     pass
        print('f12', f1, f2)

        # set lineEdit_scan_harmstart & lineEdit_scan_harmend
        self.ui.lineEdit_scan_harmstart.setText(str(f1*1e-6)) # in MHz
        self.ui.lineEdit_scan_harmend.setText(str(f2*1e-6)) # in MHz

        # update limit of active harmonic
        self.on_editingfinished_harm_freq()

        # get new data
        f, G, B = self.spectra_fit_get_data()
        
        # plot
        self.tab_spectra_fit_update_mpls(f, G, B)

    def update_lineedit_fit_span(self, f):
        ''' 
        update lineEdit_spectra_fit_span text 
        input
        f: list like data in Hz
        '''
        span = max(f) - min(f)

        # update 
        self.ui.lineEdit_spectra_fit_span.setText(UIModules.num2str((span / 1000), precision=5)) # in kHz

    # def spectra_fit_axesevent_disconnect(self, event):
    #     print('disconnect')
    #     self.mpl_disconnect_cid(self.ui.mpl_spectra_fit)

    # def spectra_fit_axesevent_connect(self, event):
    #     print('connect')
    #     self.mpl_connect_cid(self.ui.mpl_spectra_fit, self.on_fit_lims_change)
    #     # since pan changes xlim before button up, change ylim a little to trigger ylim_changed
    #     ax = self.ui.mpl_spectra_fit.ax[0]
    #     print('cn', ax.get_navigate_mode())
    #     if ax.get_navigate_mode() == 'PAN':
    #         ylim = ax.get_ylim()
    #         ax.set_ylim(ylim[0], ylim[1] * 1.01)

    def mpl_disconnect_cid(self, mpl, axis='xy'):

        if 'x' in axis:
            mpl.ax[0].callbacks.disconnect(mpl.ax[0].cidx)
        if 'y' in axis:
            mpl.ax[0].callbacks.disconnect(mpl.ax[0].cidy)

    def mpl_connect_cid(self, mpl, fun, axis='xy'):
        '''

        '''
        if 'x' in axis:
            mpl.ax[0].cidx = mpl.ax[0].callbacks.connect('xlim_changed', fun)
        if 'y' in axis:
            mpl.ax[0].cidy = self.ui.mpl_spectra_fit.ax[0].callbacks.connect('ylim_changed', fun)
    
    def mpl_set_faxis(self, ax):
        '''
        set freq axis tack as: [-1/2*span, 1/2*span] and
        freq axis label as: f (+cnter Hz)

        This can be done by
        ax.xaxis.set_major_locator(ticker.LinearLocator(3))
        in MatplotlibWidget.py module
        '''
        # get xlim
        xlim = ax.get_xlim()
        print(xlim)
        center = (xlim[0] + xlim[1]) / 2
        span = xlim[1] - xlim[0]

        # # get ticks
        # locs = ax.get_xticks()
        # labels = np.array(locs) - center
        # # set ticks
        # ax.set_xticklabels([str(l) for l in labels])

        # use offset
        # ax.ticklabel_format(useOffset=center, axis='x')
        
        # manually set
        ax.set_xticks([xlim[0], center, xlim[1]])
        #TODO following line makes the x coordinates fail
        # ax.set_xticklabels([str(-span * 0.5), '0', str(span * 0.5)])
        # set xlabel
        # ax.set_xlabel('f (+{} Hz)'.format(center))

    def mpl_sp_clr_lines_set_label(self, signal):
        '''
        clear mpl_sp<n> when the plot mode changes
        Gp, Gp+Bp, Polor
        '''

        sender = self.sender().objectName()
        print(sender)
        if (sender == 'radioButton_spectra_showGp') or (sender == 'radioButton_spectra_showBp'):
            xlabel = r'$f$ (Hz)'
            y2label = r'$B_P$ (mS)'
        elif sender == 'radioButton_spectra_showpolar':
            xlabel = r'$B_P$ (mS)'
            y2label = ''
        else:
            xlabel = r'$f$ (Hz)'
            y2label = r'$B_P$ (mS)'

        for harm in range(1, settings_init['max_harmonic']+2, 2):
            harm = str(harm)
            # clear lines
            getattr(self.ui, 'mpl_sp' + harm).clr_lines()
            # clear .t['chi']
            getattr(self.ui, 'mpl_sp' + harm).update_sp_text_chi()
            # set labels
            getattr(self.ui, 'mpl_sp' + harm).ax[0].set_xlabel(xlabel)
            getattr(self.ui, 'mpl_sp' + harm).ax[1].set_ylabel(y2label)

            getattr(self.ui, 'mpl_sp' + harm).canvas.draw()

    def mpl_sp_clr_chis(self):
        for harm in range(1, settings_init['max_harmonic']+2, 2):
            harm = str(harm)
            # clear .t['chi']
            getattr(self.ui, 'mpl_sp' + harm).update_sp_text_chi()



    def on_clicked_pushButton_spectra_fit_fit(self):
        '''
        fit Gp, Bp data shown in mpl_spectra_fit ('lG' and 'lB')
        '''
        # get data in tuple (x, y)
        data_lG, data_lB = self.ui.mpl_spectra_fit.get_data(ls=['lG', 'lB'])

        if len(data_lG[0]) == 0: # no data
            return

        # factor = self.get_harmdata('spinBox_harmfitfactor')

        # get guessed value of cen and wid

        ## fitting peak
        print('main set harm', self.settings_harm)
        self.peak_tracker.update_input(self.settings_chn['name'], self.settings_harm, data_lG[0], data_lG[1], data_lB[1], self.settings['harmdata'], self.settings['freq_span'])

        fit_result = self.peak_tracker.peak_fit(self.settings_chn['name'], self.settings_harm, components=True)
        print(fit_result['v_fit'])
        # print(fit_result['comp_g'])
        # plot fitted data
        self.ui.mpl_spectra_fit.update_data(('lGfit',data_lG[0], fit_result['fit_g']), ('lBfit',data_lB[0], fit_result['fit_b']))
        self.ui.mpl_spectra_fit_polar.update_data(('lfit',fit_result['fit_g'], fit_result['fit_b']))

        # clear l.['temp'][:]
        self.ui.mpl_spectra_fit.del_templines()
        self.ui.mpl_spectra_fit_polar.del_templines()
        # add devided peaks
        self.ui.mpl_spectra_fit.add_temp_lines(self.ui.mpl_spectra_fit.ax[0], xlist=[data_lG[0]] * len(fit_result['comp_g']), ylist=fit_result['comp_g'])
        self.ui.mpl_spectra_fit_polar.add_temp_lines(self.ui.mpl_spectra_fit_polar.ax[0],xlist=fit_result['comp_g'], ylist=fit_result['comp_b'])

        # update lsp
        factor_span = self.peak_tracker.get_output(key='factor_span', chn_name=self.settings_chn['name'], harm=self.settings_harm)
        gc_list = [fit_result['v_fit']['g_c']['value']] * 2 # make its len() == 2

        print(factor_span)
        print(gc_list)

        # sp_fit
        self.ui.mpl_spectra_fit.update_data(('lsp', factor_span, gc_list))

        # sp_polar
        print(len(data_lG[0]))
        print(factor_span)
        idx = np.where((data_lG[0] >= factor_span[0]) & (data_lG[0] <= factor_span[1])) # determine the indices by f (data_lG[0])
        
        self.ui.mpl_spectra_fit_polar.update_data(('lsp', fit_result['fit_g'][idx], fit_result['fit_b'][idx]))

        if self.get_spectraTab_mode() == 'center': # center mode
            # update strk
            cen_trk_freq = fit_result['v_fit']['cen_trk']['value']
            cen_trk_G = self.peak_tracker.get_output(key='gmod', chn_name=self.settings_chn['name'], harm=self.settings_harm).eval(
                self.peak_tracker.get_output(key='params', chn_name=self.settings_chn['name'], harm=self.settings_harm),
                x=cen_trk_freq
            ) 

            print(cen_trk_freq)
            print(cen_trk_G)

            self.ui.mpl_spectra_fit.update_data(('strk', cen_trk_freq, cen_trk_G))

        # update srec
        cen_rec_freq = fit_result['v_fit']['cen_rec']['value']
        cen_rec_G = self.peak_tracker.get_output(key='gmod', chn_name=self.settings_chn['name'], harm=self.settings_harm).eval(
            self.peak_tracker.get_output(key='params', chn_name=self.settings_chn['name'], harm=self.settings_harm),
            x=cen_rec_freq
        ) 

        print(cen_rec_freq)
        print(cen_rec_G)

        self.ui.mpl_spectra_fit.update_data(('srec', cen_rec_freq, cen_rec_G))

        # add results to textBrowser_spectra_fit_result
        if self.get_spectraTab_mode() == 'refit': # refit mode
            # save scan data to data_saver 
            self.data_saver.update_refit_data(
                self.active['chn_name'], 
                self.get_active_queueid_from_l_harm_ind(), 
                [self.active['harm']], 
                fs=[fit_result['v_fit']['cen_rec']['value']], # fs
                gs=[fit_result['v_fit']['wid_rec']['value']], # gs = half_width 
            )
            # update mpl_plt12
            self.update_mpl_plt12()

    def pick_manual_refit(self):
        '''
        manual refit process after manual refit context menu triggered
        '''

        self.disable_widgets('manual_refit_enable_disable_harmtree_list')
        # set pushButton_manual_refit checked 
        self.show_widgets('manual_refit_enable_disable_list')
        self.ui.pushButton_manual_refit.setChecked(True)
        self.init_manual_refit()

        # get data from data saver
        f, G, B = self.get_active_raw()
        print(len(f), len(G), len(B))

        # update raw
        self.tab_spectra_fit_update_mpls(f, G, B)






    def get_active_queueid_from_l_harm_ind(self):
        '''
        get queue_id from data_saver by
        l_str: str. line 'l' or 'lm'
        harm: str. 
        ind: index
        return queue_id
        '''
        if self.active['l_str'] == 'l': # showing all data
            queue_list = self.data_saver.get_queue_id_marked_rows(self.active['chn_name'], dropnanrow=False)
        elif self.active['l_str'] == 'lm': # showing marked data
            queue_list = self.data_saver.get_queue_id_marked_rows(self.active['chn_name'], dropnanrow=True)
        return queue_list[self.active['ind']]

    def get_active_raw(self):
        '''
        get raw data of active from data_saver
        '''
        queue_id = self.get_active_queueid_from_l_harm_ind()
        f, G, B = self.data_saver.get_raw(self.active['chn_name'], queue_id, self.active['harm'])


        return f, G, B

    def init_manual_refit(self):
        '''
        initiate widgets for manual refit
        '''
        print('refit isChecked', self.ui.pushButton_manual_refit.isChecked())
        if self.ui.pushButton_manual_refit.isChecked():
            # make a copy of self.freq_span and self.harmdata for refit
            print('copy to active')
            self.settings['freq_span']['refit'] = self.settings['freq_span'][self.active['chn_name']]
            self.settings['harmdata']['refit'] = self.settings['harmdata'][self.active['chn_name']]

            # add manual refit tab to tabWidget_settings_settings_samprefchn
            self.add_manual_refit_tab(True)
            print(self.settings_chn)

            # self.ui.tabWidget_settings_settings_samprefchn.setCurrentIndex(-1) # show manual refit buttons and emit update_settings_chn
            self.ui.tabWidget_settings_settings_harm.setCurrentIndex((int(self.active['harm'])-1)/2) # set to active harm and emit update_settings_chn

            # # update treeWidget_settings_settings_harmtree
            # self.update_harmonic_tab()

            # change tabWidget_settings to settings tab
            self.ui.tabWidget_settings.setCurrentWidget(self.ui.tab_settings_settings)

        else:
            self.hide_widgets('manual_refit_enable_disable_list')
            # delete the refit tab
            self.enable_widgets('manual_refit_enable_disable_harmtree_list')
            self.add_manual_refit_tab(False)
            # reset index
            self.ui.tabWidget_settings_settings_samprefchn.setCurrentIndex(0)
            
            # clear mpl
            self.ui.mpl_spectra_fit.clr_lines()
            self.ui.mpl_spectra_fit_polar.clr_lines()





    def add_manual_refit_tab(self, signal):
        '''
        add/delete manual refit tab to tabWidget_settings_settings_samprefchn
        self.add_manual_refit_tab(True)
        signal: True, add; False, delete
        '''
        if signal:
                if self.ui.tabWidget_settings_settings_samprefchn.currentIndex() != self.ui.tabWidget_settings_settings_samprefchn.indexOf(self.ui.tab_settings_settings_harmchnrefit): # refit is current tab
                    self.ui.tabWidget_settings_settings_samprefchn.addTab(self.ui.tab_settings_settings_harmchnrefit, 'Refit')
                    self.ui.tabWidget_settings_settings_samprefchn.setCurrentWidget(self.ui.tab_settings_settings_harmchnrefit)
        else:
            self.ui.tabWidget_settings_settings_samprefchn.removeTab(self.ui.tabWidget_settings_settings_samprefchn.indexOf(
                self.ui.tab_settings_settings_harmchnrefit
                )
            )


    ###### data display functions #########
    def get_axis_settings(self, name):
        '''
        get axis settings from treeWidget_settings_settings_plots
        return

        '''
        if name == 'comboBox_timeunit':
            return self.settings.get('comboBox_timeunit', 'm')
        elif name == 'comboBox_tempunit':
            return self.settings.get('comboBox_tempunit', 'C')
        elif name == 'comboBox_xscale':
            return self.settings.get('comboBox_xscale', 'linear')
        elif name == 'comboBox_yscale':
            return self.settings.get('comboBox_yscale', 'linear')
        elif name == 'checkBox_linkx':
            return self.settings.get('checkBox_linkx', True)
        else:
            return None

    def get_plt_opt(self, plt_str):
        '''
        get option for data plotting
        plt_str: 'plt1' or 'plt2'
        return itemdata splited by '_'
        '''
        return [self.settings.get('comboBox_' + plt_str + '_optsy'), self.settings.get('comboBox_' + plt_str + '_optsx')] # use the first one if failed
    
    def get_plt_harms(self, plt_str):
        '''
        get harmonics to plot
        plt_str: 'plt1' or 'plt2'
        return list of harmonics in strings
        '''
        return [str(harm) for harm in range(1, settings_init['max_harmonic']+2, 2) if self.settings.get('checkBox_' + plt_str + '_h' + str(harm), False)]

    def get_plt_chnname(self, plt_str):
        '''
        get channel name to plot
        plt_str: 'plt1' or 'plt2'
        return a str ('samp' or 'ref')
        '''
        if self.settings.get('radioButton_' + plt_str + '_samp'):
            return 'samp'
        elif self.settings.get('radioButton_' + plt_str + '_ref'):
            return 'ref'
        else:
            return 'samp'
       
    def update_mpl_plt12(self):
        '''
        update mpl_plt1 and mpl_plt2
        '''
        self.update_mpl_dataplt(plt_str='plt1')
        self.update_mpl_dataplt(plt_str='plt2')

    def update_mpl_plt1(self):
        '''
        update mpl_plt1
        '''
        self.update_mpl_dataplt(plt_str='plt1')

    def update_mpl_plt2(self):
        '''
        update mpl_plt2
        '''
        self.update_mpl_dataplt(plt_str='plt2')

    def update_mpl_dataplt(self, plt_str='none'):
        '''
        update mpl_<plt_str> by the UI settings
        plt_str: str of 'plt1' or 'plt2'
        '''

        print('showall', self.settings['radioButton_data_showall'])
        print('showmarked', self.settings['radioButton_data_showmarked'])

        if plt_str != 'plt1' and plt_str != 'plt2': # n is not in the UI
            # do nothing
            return
        
        if not self.data_saver.mode: # no data
            return

        # get plt opts
        plt_opt = self.get_plt_opt(plt_str) # split str to [y, x]
        print('opt', plt_opt)
        if plt_opt[0] == 'none':
            # no data need to be plotted
            return
        # get checked harmonics
        plt_harms = self.get_plt_harms(plt_str) 
        print('plt_harms', plt_harms)
        if not plt_harms: # no harmonic to plot
            return

        # get plot channel
        plt_chnname = self.get_plt_chnname(plt_str)
        
        # get timeunit
        timeuint = self.settings['comboBox_timeunit']
        # get tempunit
        tempunit = self.settings['comboBox_tempunit']
        print(timeuint)
        print(tempunit)

        # axis scale will be auto changed when comboBox_plt<n>_opts changed. We don't need to get it here

        # from tabWidget_settings
        if self.show_marked_data(): # show marked data only
            # mark = True
            if self.data_saver.with_marks(plt_chnname):
                line_group = 'lm'
                mark = True
            else:
                line_group = 'l'
                mark = False
        else: # show all data
            mark = False
            line_group = 'l'

        # get y data
        ydata = self.get_data_by_typestr(plt_opt[0], plt_chnname, mark=mark, unit_t=timeuint, unit_temp=tempunit)

        # get x data. normally t
        xdata = self.get_data_by_typestr(plt_opt[1], plt_chnname, mark=mark, unit_t=timeuint, unit_temp=tempunit)

        print('------xdata--------')
        print(xdata)
        print('-------------------')
        print('------ydata--------')
        print(ydata)
        print('-------------------')

        # prepare data for plotting
        data_list = self.prepare_harm_data_for_mpl_update(plt_chnname, plt_harms, line_group, xdata, ydata, show_marked_when_all=True)
        
        # update mpl_<plt_str>
        getattr(self.ui, 'mpl_' + plt_str).update_data(*data_list)
        
        # # get keys of harms don't want to plot
        # clr_list = ['l'+str(harm) for harm in range(1, settings_init['max_harmonic']+2, 2) if not self.settings.get('checkBox_' + plt_str + '_h' + str(harm), False)] 
        # # clear harmonics don't plot
        # getattr(self.ui, 'mpl_' + plt_str).clr_lines(clr_list)


    def prepare_harm_data_for_mpl_update(self, plt_chnname, plt_harms, line_group, xdata, ydata, show_marked_when_all=True):
        '''
        devide xdata/ydata by harmonics and return a list of tuples for data_saver.update_data
        '''
        data_list = []

        if show_marked_when_all: 
            mark_df = self.data_saver.get_list_column_to_columns_marked_rows(plt_chnname, 'marks', mark=False, dropnanrow=False, deltaval=False, norm=False)            
        for harm in plt_harms: # selected
            harm = str(harm)
            # set xdata for harm
            print(xdata.shape)
            if len(xdata.shape) == 1: # one column e.g.: tuple (1,) is series
                harm_xdata = xdata
            else: # multiple columns
                harm_xdata = xdata.filter(like=harm, axis=1).squeeze() # convert to series
            # set ydata for harm
            if len(ydata.shape) == 1: # series
                harm_ydata = ydata
            else: # multiple columns
                harm_ydata = ydata.filter(like=harm, axis=1).squeeze() # convert to series
            data_list.append((line_group+harm, harm_xdata, harm_ydata))

            if show_marked_when_all:
                ## display marked data (solid) along with all data (open) (can be removed if don't like)
                if self.settings['radioButton_data_showall']:
                    if self.data_saver.with_marks(plt_chnname):
                        mark_list = mark_df['mark'+harm] == 1
                        print('mark_list', mark_list)
                    else: 
                        mark_list = []
                    if isinstance(mark_list, pd.Series):
                        data_list.append(('lm'+harm, harm_xdata[mark_list], harm_ydata[mark_list]))
        return data_list



    def get_data_by_typestr(self, typestr, chn_name, mark=False, unit_t=None, unit_temp=None):
        '''
        get data of all harmonics from data_saver by given type (str)
        str: 'df', 'dfn', 'mdf', 'mdfn', 'dg', 'dgn', 'f', 'g', 'temp', 't'
        return: data
        '''

        print(typestr)
        if typestr in ['df', 'delfs']: # get delf
            data = self.data_saver.get_list_column_to_columns_marked_rows(chn_name, 'fs', mark=mark, dropnanrow=False, deltaval=True, norm=False)
        elif 'mdf' == typestr: # get delf
            data = self.data_saver.get_list_column_to_columns_marked_rows(chn_name, 'fs', mark=mark, dropnanrow=False, deltaval=True, norm=False)
            data = self.data_saver.minus_columns(data)
        elif typestr in ['dg', 'delgs']: # get delg
            data = self.data_saver.get_list_column_to_columns_marked_rows(chn_name, 'gs', mark=mark, dropnanrow=False, deltaval=True, norm=False)
        elif 'dfn' == typestr: # get delfn
            data = self.data_saver.get_list_column_to_columns_marked_rows(chn_name, 'fs', mark=mark, dropnanrow=False, deltaval=True, norm=True)
        elif 'mdfn' == typestr: # get delfn
            data = self.data_saver.get_list_column_to_columns_marked_rows(chn_name, 'fs', mark=mark, dropnanrow=False, deltaval=True, norm=True)
            data = self.data_saver.minus_columns(data)
        elif 'dgn' == typestr: # get delgn
            data = self.data_saver.get_list_column_to_columns_marked_rows(chn_name, 'gs', mark=mark, dropnanrow=False, deltaval=True, norm=True)
        elif 'f' == typestr: # get f
            data = self.data_saver.get_list_column_to_columns_marked_rows(chn_name, 'fs', mark=mark, dropnanrow=False, deltaval=False, norm=False)
        elif 'g' == typestr: # get g
            data = self.data_saver.get_list_column_to_columns_marked_rows(chn_name, 'gs', mark=mark, dropnanrow=False, deltaval=False, norm=False)
        elif 't' == typestr: # get t
            data = self.data_saver.get_t_marked_rows(chn_name, dropnanrow=False, unit=unit_t)
        elif 'temp' == typestr: # get temp
            data = self.data_saver.get_temp_by_uint_marked_rows(chn_name, dropnanrow=False, unit=unit_temp)
        elif 'idx' == typestr: # get indices
            data = self.data_saver.get_queue_id_marked_rows(chn_name, dropnanrow=False)
        
        return data


    def update_data_axis(self, signal):

        sender_name = self.sender().objectName()
        print(sender_name)

        # check which plot to update
        if 'plt1' in sender_name or 'plt2' in sender_name:# signal sent from one of the plots
            plt_str = sender_name.split('_')[1] # plt1 or plt2

            # plot option str in list [y, x]
            plt_opt = self.get_plt_opt(plt_str)
            print(plt_opt)

            if 't' in plt_opt: # there is time axis in the plot
                self.update_time_unit(plt_str, plt_opt)
            
            if 'temp' in plt_opt: # htere is temp axis in the plot
                self.update_temp_unit(plt_str, plt_opt)
            
            if plt_opt[0] not in ['t', 'temp']: # other type in y-axis w/o changing the unit
                ylabel = settings_init['data_plt_axis_label'].get(plt_opt[0], 'label error')
                # set y labels
                getattr(self.ui, 'mpl_' + plt_str).ax[0].set_ylabel(ylabel)
                getattr(self.ui, 'mpl_' + plt_str).canvas.draw()

            if plt_opt[1] not in ['t', 'temp']: # other type in x-axis w/o changing the unit
                xlabel = settings_init['data_plt_axis_label'].get(plt_opt[0], 'label error')
                # set x labels
                getattr(self.ui, 'mpl_' + plt_str).ax[0].set_xlabel(xlabel)
                getattr(self.ui, 'mpl_' + plt_str).canvas.draw()

        if sender_name == 'comboBox_timeunit': # update both axises of mpl_plt1 & mpl_plt2
            for plt_str in ['plt1', 'plt2']: 
                # plot option str in list [y, x]
                plt_opt = self.get_plt_opt(plt_str)
                if 't' in plt_opt: # there is time axis in the plot (plt_opt[0] == 't' or plt_opt[1] == 't')
                    self.update_time_unit(plt_str, plt_opt)
                    # getattr(self.ui, 'mpl_' + plt_str).canvas.draw()
                

        if sender_name == 'comboBox_tempunit': # update both axises of mpl_plt1 & mpl_plt2
            for plt_str in ['plt1', 'plt2']: 
                # plot option str in list [y, x]
                plt_opt = self.get_plt_opt(plt_str)
                if 'temp' in plt_opt: # there is temp axis in the plot
                    self.update_temp_unit(plt_str, plt_opt)
                    # getattr(self.ui, 'mpl_' + plt_str).canvas.draw()

        if sender_name == 'comboBox_xscale': # update both axises of mpl_plt1 & mpl_plt2
            for plt_str in ['plt1', 'plt2']: 
                # plot option str in list [y, x]
                getattr(self.ui, 'mpl_' + plt_str).ax[0].set_xscale(self.sender().itemData(signal))
                getattr(self.ui, 'mpl_' + plt_str).canvas.draw()

        if sender_name == 'comboBox_yscale': # update both axises of mpl_plt1 & mpl_plt2
            for plt_str in ['plt1', 'plt2']: 
                # plot option str in list [y, x]
                getattr(self.ui, 'mpl_' + plt_str).ax[0].set_yscale(self.sender().itemData(signal))
                getattr(self.ui, 'mpl_' + plt_str).canvas.draw()

        if sender_name == 'checkBox_linkx': # link x axis of mpl_plt1 & mpl_plt2
            if signal:
                self.ui.mpl_plt1.ax[0].get_shared_x_axes().join(
                    self.ui.mpl_plt1.ax[0],
                    self.ui.mpl_plt2.ax[0]
                )
            else:
                self.ui.mpl_plt1.ax[0].get_shared_x_axes().remove(
                    self.ui.mpl_plt2.ax[0]
                )

            self.ui.mpl_plt1.canvas.draw()
            self.ui.mpl_plt2.canvas.draw()

    # def set_plt2_on_plt1_xlim_change(self):
    #     # get mpl_plt1 xlims
    #     xlim = self.ui.mpl_plt1.ax[0].get_xlim()
    #     # set mpl_plt2 xlim
    #     self.ui.mpl_plt2.ax[0].set_xlim(xlim)

    # def set_plt1_on_plt2_xlim_change(self):
    #     # get mpl_plt2 xlims
    #     xlim = self.ui.mpl_plt2.ax[0].get_xlim()
    #     # set mpl_plt1 xlim
    #     self.ui.mpl_plt1.ax[0].set_xlim(xlim)


    def show_marked_data(self):
        '''
        check radiobuttons and return mode to display data
        '''
        if self.settings['radioButton_data_showall']: # show all data
            mark = False
            line_group = 'l'
        elif self.settings['radioButton_data_showmarked']: # show marked data only
            mark = True

        return mark


    def update_time_unit(self, plt_str, plt_opt):
        '''
        update time unit in mpl_<plt_str> x/y label
        plt_str: 'plt1' or 'plt2'
        plt_opt: list of plot type str [y, x]
        NOTE: check if time axis in plot_opt before sending to this function
        '''
        print(plt_str)
        print(plt_opt)
        if 't' not in plt_opt:
            return
    
        if 't' == plt_opt[0]: # is y axis
            ylabel = settings_init['data_plt_axis_label'].get(plt_opt[0], 'label error')
            print(ylabel)
            ylabel = self.time_str_unit_replace(ylabel)
            print(ylabel)
            getattr(self.ui, 'mpl_' + plt_str).ax[0].set_ylabel(ylabel)
            print(getattr(self.ui, 'mpl_' + plt_str).ax[0].get_ylabel())
        if 't' == plt_opt[1]: # is x axis
            xlabel = settings_init['data_plt_axis_label'].get(plt_opt[1], 'label error')
            xlabel = self.time_str_unit_replace(xlabel)
            getattr(self.ui, 'mpl_' + plt_str).ax[0].set_xlabel(xlabel)
            print(getattr(self.ui, 'mpl_' + plt_str).ax[0].get_xlabel())
            print(xlabel)
        getattr(self.ui, 'mpl_' + plt_str).canvas.draw()


    def update_temp_unit(self, plt_str, plt_opt):
        '''
        update temp unit in mpl_<plt_str> x/y label
        plt_str: 'plt1' or 'plt2'
        plt_opt: list of plot type str [y, x]
        '''
        print(plt_str)
        print(plt_opt)
        if 'temp' not in plt_opt:
            return
        # idx_temp, = [i for i in range(len(plt_opt)) if plt_opt[i] == 'temp']
        # print(idx_temp)

        if 'temp' == plt_opt[0]: # is y axis
            ylabel = settings_init['data_plt_axis_label'].get(plt_opt[0], 'label error')
            ylabel = self.temp_str_unit_replace(ylabel)
            getattr(self.ui, 'mpl_' + plt_str).ax[0].set_ylabel(ylabel)
            print(ylabel)
        if 'temp' == plt_opt[1]: # is x axis
            xlabel = settings_init['data_plt_axis_label'].get(plt_opt[1], 'label error')
            xlabel = self.temp_str_unit_replace(xlabel)
            getattr(self.ui, 'mpl_' + plt_str).ax[0].set_xlabel(xlabel)
            print(xlabel)
        getattr(self.ui, 'mpl_' + plt_str).canvas.draw()


    def time_str_unit_replace(self, time_str):
        '''
        replace 'unit' in time_str and
        return time_str with uint set in UI
        '''
        timeunit = self.get_axis_settings('comboBox_timeunit')
        print(timeunit)
        if timeunit == 's': 
            timeunit = r's'
        elif timeunit == 'm': 
            timeunit = r'min'
        elif timeunit == 'h': 
            timeunit = r'h'        
        elif timeunit == 'd': 
            timeunit = r'day'        
        return time_str.replace('unit', timeunit)


    def temp_str_unit_replace(self, temp_str):
        '''
        replace 'unit' in temp_str and
        return temp_str with uint set in UI
        '''
        tempunit = self.get_axis_settings('comboBox_tempunit')
        if tempunit == 'C': 
            tempunit = r'$\degree$C'
        elif tempunit == 'K': 
            tempunit = r'K'
        elif tempunit == 'F': 
            tempunit = r'$\degree$F'
        print(tempunit)

        return temp_str.replace('unit', tempunit)


    def clr_mpl_harm(self):
        '''
        clear 'l' and 'lm' lines of harm (str) in mpl_<plt_str>
        '''
        sender = self.sender().objectName()
        print(sender)
        str_list = sender.split('_')
        print(str_list)
        print(sender, self.settings[sender])

        if not self.settings[sender]: # unchecked
            self.clr_mpl_l(str_list[1], line_group_list=['l', 'lm'], harm_list=[sender[-1]]) # sender[-1] is the harm from checkBox_plt<n>_h<harm>

    def set_mpl_lm_style(self, signal):
        line_list = ['lm'+str(i) for i in range(1, settings_init['max_harmonic']+2, 2)]
        if signal:
            self.ui.mpl_plt1.change_style(line_list, linestyle='-')
            self.ui.mpl_plt2.change_style(line_list, linestyle='-')
        else:
            self.ui.mpl_plt1.change_style(line_list, linestyle='none')
            self.ui.mpl_plt2.change_style(line_list, linestyle='none')

    def clr_mpl_l12(self):
        # self.clr_mpl_l('plt1')
        # self.clr_mpl_l('plt2')
        self.ui.mpl_plt1.clr_lines()
        self.ui.mpl_plt2.clr_lines()

    def clr_mpl_l(self, plt_str, line_group_list=['l'], harm_list=[]):
        '''
        clear .l['l<n>'] in mpl_<plt_str>
        ''' 
        if not harm_list:
            harm_list = [str(harm) for harm in range(1, settings_init['max_harmonic']+2, 2)]
        for line_group in line_group_list:
            # get keys of harms don't want to plot
            clr_list = [line_group+harm for harm in harm_list] 
            # clear harmonics don't plot
            getattr(self.ui, 'mpl_' + plt_str).clr_lines(clr_list)

    def mpl_data_open_custom_menu(self, position, mpl, plt_str):
        '''
        check which menu to open: mpl_data_open_selector_menu or mpl_data_pen_picker_menu
        '''
        print('customMenu')
        print(position)
        print(mpl)
        print(plt_str)

        if not self.data_saver.path:
            return

        if mpl.sel_mode == 'selector':
            self.mpl_data_open_selector_menu(position, mpl, plt_str)
        elif mpl.sel_mode == 'picker':
            self.mpl_data_open_picker_menu(position, mpl, plt_str)
        # else:
        #     self.mpl_data_open_selector_menu(position, mpl, plt_str)

        # # update display
        # mpl.canvas.draw()
        print('this should run after contextmenu')
        self.update_mpl_plt12()
 
    def mpl_data_open_selector_menu(self, position, mpl, plt_str):
        '''
        function to execute the selector custom context menu for selector
        '''
        print('selector')
        print(position)
        print(mpl)
        print(plt_str)
        
        # get .l['ls<n>'] data
        # dict for storing the selected indices
        sel_idx_dict = {}
        selflg = False # flag for if sel_data_dict is empty
        plt_harms = self.get_plt_harms(plt_str) # get checked harmonics
        for harm in plt_harms:
            harm = str(harm)
            print('harm', harm)
            # print(mpl.get_data(ls=['ls'+harm]))
            harm_sel_data, = mpl.get_data(ls=['ls'+harm]) # (xdata, ydata)
            print(harm_sel_data)
            print(harm_sel_data[0])
            if isinstance(harm_sel_data[0], pd.Series) and harm_sel_data[0].shape[0] > 0: # data is not empty
                harm_sel_idx = harm_sel_data[0].index # get indices from xdata
                print(harm_sel_idx)
                sel_idx_dict[harm] = harm_sel_idx
                selflg = True
        print(sel_idx_dict)
        # if no selected data return
        if not selflg:
            # pass
            return

        print('selflg', selflg)

        # get channel name
        chn_name = self.get_plt_chnname(plt_str)
        chn_queue_list = list(self.data_saver.get_queue_id(chn_name).tolist()) # list of available index in the target chn

        # create contextMenu
        selmenu = QMenu('selmenu', self)

        menuMark = QMenu('Mark', self)
        actionMark_all = QAction('Mark all showing data', self)
        actionMark_all.triggered.connect(lambda: self.data_saver.selector_mark_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'all', chn_queue_list), 1))
        if selflg:
            actionMark_selpts = QAction('Mark selected points', self)
            actionMark_selpts.triggered.connect(lambda: self.data_saver.selector_mark_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selpts', chn_queue_list), 1))
            actionMark_selidx = QAction('Mark selected indices', self)
            actionMark_selidx.triggered.connect(lambda: self.data_saver.selector_mark_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selidx', chn_queue_list), 1))
            actionMark_selharm = QAction('Mark selected harmonics', self)
            actionMark_selharm.triggered.connect(lambda: self.data_saver.selector_mark_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selharm', chn_queue_list), 1))

        menuMark.addAction(actionMark_all)
        if selflg:
            menuMark.addAction(actionMark_selpts)
            menuMark.addAction(actionMark_selidx)
            menuMark.addAction(actionMark_selharm)

        menuUnmark = QMenu('Unmark', self)
        actionUnmark_all = QAction('Unmark all showing data', self)
        actionUnmark_all.triggered.connect(lambda: self.data_saver.selector_mark_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'all', chn_queue_list), 0))
        if selflg:
            actionUnmark_selpts = QAction('Unmark selected points', self)
            actionUnmark_selpts.triggered.connect(lambda: self.data_saver.selector_mark_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selpts', chn_queue_list), 0))
            actionUnmark_selidx = QAction('Unmark selected indices', self)
            actionUnmark_selidx.triggered.connect(lambda: self.data_saver.selector_mark_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selidx', chn_queue_list), 0))
            actionUnmark_selharm = QAction('Unmark selected harmonics', self)
            actionUnmark_selharm.triggered.connect(lambda: self.data_saver.selector_mark_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selharm', chn_queue_list), 0))

        menuUnmark.addAction(actionUnmark_all)
        if selflg:
            menuUnmark.addAction(actionUnmark_selpts)
            menuUnmark.addAction(actionUnmark_selidx)
            menuUnmark.addAction(actionUnmark_selharm)

        menuDel = QMenu('Delete', self)
        actionDel_all = QAction('Delete all showing data', self)
        actionDel_all.triggered.connect(lambda: self.data_saver.selector_del_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'all', chn_queue_list)))
        if selflg:
            actionDel_selpts = QAction('Delete selected points', self)
            actionDel_selpts.triggered.connect(lambda: self.data_saver.selector_del_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selpts', chn_queue_list)))
            actionDel_selidx = QAction('Delete selected indices', self)
            actionDel_selidx.triggered.connect(lambda: self.data_saver.selector_del_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selidx', chn_queue_list)))
            actionDel_selharm = QAction('Delete selected harmonics', self)
            actionDel_selharm.triggered.connect(lambda: self.data_saver.selector_del_sel(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selharm', chn_queue_list)))

        menuDel.addAction(actionDel_all)
        if selflg:
            menuDel.addAction(actionDel_selpts)
            menuDel.addAction(actionDel_selidx)
            menuDel.addAction(actionDel_selharm)

        menuRefit = QMenu('Refit', self)
        actionRefit_all = QAction('Refit all showing data', self)
        actionRefit_all.triggered.connect(lambda: self.data_refit(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'all', chn_queue_list)))
        if selflg:
            actionRefit_selpts = QAction('Refit selected points', self)
            actionRefit_selpts.triggered.connect(lambda: self.data_refit(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selpts', chn_queue_list)))
            actionRefit_selidx = QAction('Refit selected indices', self)
            actionRefit_selidx.triggered.connect(lambda: self.data_refit(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selidx', chn_queue_list)))
            actionRefit_selharm = QAction('Refit selected harmonics', self)
            actionRefit_selharm.triggered.connect(lambda: self.data_refit(chn_name, UIModules.sel_ind_dict(plt_harms, sel_idx_dict, 'selharm', chn_queue_list)))

        menuRefit.addAction(actionRefit_all)
        if selflg:
            menuRefit.addAction(actionRefit_selpts)
            menuRefit.addAction(actionRefit_selidx)
            menuRefit.addAction(actionRefit_selharm)

        selmenu.addMenu(menuMark)
        selmenu.addMenu(menuUnmark)
        selmenu.addMenu(menuDel)
        selmenu.addMenu(menuRefit)
        
        #else, find out the indices and do mark/unmark/delete
        selmenu.exec_(mpl.canvas.mapToGlobal(position))


    def mpl_data_open_picker_menu(self, position, mpl, plt_str):
        '''
        function to execute the picker custom context menu for selector
        '''
        print('picker customMenu')
        print(position)
        print(mpl)
        print(plt_str)
        
        # get .l['lp'] data
        pk_data, = mpl.get_data(ls=['lp']) # (xdata, ydata)
        print(pk_data)
        print(pk_data[0])
        print(type(pk_data))
        print(type(pk_data[0]))
        print(isinstance(pk_data[0], float))
        print(isinstance(pk_data[0], np.float))
        print(isinstance(pk_data[0], np.float64))
        if isinstance(pk_data[0], float): # data is not empty
            label = mpl.l['lp'][0].get_label()
            line, ind = label.split('_')
            l, harm = line[:-1], line[-1]
            print(line)
            print(l, harm)
            print(ind)

            self.active['chn_name'] = self.get_plt_chnname(plt_str)
            self.active['harm'] = harm
            self.active['plt_str'] = plt_str
            self.active['l_str'] = l
            self.active['ind'] = int(ind)

            print(self.active)

            # get channel name
            chn_name = self.get_plt_chnname(plt_str)

            # create contextMenu
            pkmenu = QMenu('pkmenu', self)

            actionManual_fit = QAction('Manual fit', self)
            actionManual_fit.triggered.connect(self.pick_manual_refit) 

            actionManual_fit = QAction('Manual fit', self)
            actionManual_fit.triggered.connect(self.pick_manual_refit) 

            pkmenu.addAction(actionManual_fit)

            pkmenu.exec_(mpl.canvas.mapToGlobal(position))

        else: 
            # nothing to do
            pass


    def mech_solve_all(self):
        queue_ids = self.data_saver.get_queue_id_marked_rows(self.mech_chn, dropnanrow=False)
        self.mech_solve_chn(self.mech_chn, queue_ids)


    def mech_solve_marked(self):
        queue_ids = self.data_saver.get_queue_id_marked_rows(self.mech_chn, dropnanrow=True)       
        self.mech_solve_chn(self.mech_chn, queue_ids)


    def update_mechanics_chn(self):
        '''
        update self.mech_chn
        '''
        idx = self.ui.tabWidget_mechanics_chn.currentIndex()
        print(idx)
        if idx == 0: # samp
            self.mech_chn = 'samp'
        elif idx == 1: # ref
            self.mech_chn = 'ref'


    def update_qcm_rh(self):
        '''
        update reference harmonic in qcm
        '''
        self.qcm.rh = int(self.settings['comboBox_settings_mechanics_refG'])


    def mech_solve_chn(self, chn_name, queue_ids):
        '''
        send the data to qcm module to solve in secquence by queue_ids and
        save the returned mechanic data to data_saver
        '''

        if not self.data_saver.path:
            print('No data available!')
            return
        # get f1
        f1 = self.data_saver.get_fg_ref(chn_name, harms=[1])['f0'][0]
        # set f1 to qcm module
        self.qcm.f1 = f1

        self.qcm.rh = int(self.settings['comboBox_settings_mechanics_refG'])
        rh = self.qcm.rh # reference harmonic

        print('f1', self.qcm.f1, 'rh', rh)
        # get nhcalc
        nhcalc_list = self.gen_nhcalc_list()
        # get qcm data (columns=['queue_id', 't', 'temp', 'marks', 'fstars', 'fs', 'gs', 'delfstars', 'delfs', 'delgs'])
        # 'delf', 'delgs' may not necessary
        qcm_df = self.data_saver.df_qcm(chn_name)

        # do calc with each nhcalc
        for nhcalc in nhcalc_list:
            mech_df = self.data_saver.update_mech_df_shape(chn_name, nhcalc, rh)

            print(mech_df)

            # if live update is not needed, use QCM.analyze to replace. the codes should be the same
            nh = QCM.nhcalc2nh(nhcalc)
            for queue_id in queue_ids: # iterate all ids
                print('queue_id', queue_id)
                # print('qcm_df', qcm_df)
                print(type(qcm_df))
                # queue index
                idx = qcm_df[qcm_df.queue_id == queue_id].index.astype(int)[0]
                # idx = qcm_df[qcm_df.queue_id == queue_id].index
                print('index', qcm_df.index)
                print('idx', idx)
                # qcm data of queue_id
                qcm_queue = qcm_df.loc[[idx], :].copy() # as a dataframe
                # mechanic data of queue_id
                mech_queue = mech_df.loc[[idx], :].copy()  # as a dataframe
                print(mech_queue)

                # obtain the solution for the properties
                if self.qcm.all_nhcaclc_harm_not_na(nh, qcm_queue):
                    # solve a single queue
                    mech_queue = self.qcm.solve_single_queue(nh, qcm_queue, mech_queue)
                    # save back to mech_df
                    print(mech_df.loc[[idx], :].to_dict())
                    print(mech_queue.to_dict())
                    # set mech_queue index the same as where it is from for update
                    print(mech_df.delg_calcs[idx])
                    mech_queue.index = [idx]
                    mech_df.update(mech_queue)
                    # print(mech_df)
                    print(mech_df.delg_calcs[idx])

                    if self.settings['checkBox_settings_mech_liveupdate']: # live update
                        # update tableWidget_spectra_mechanics_table
                        self.update_spectra_mechanics_table(chn_name, nhcalc, rh, queue_id, qcm_queue, mech_queue)

                else:
                    # since the df already initialized with nan values, nothing to do here
                    pass

            # save back to data_saver
            self.data_saver.update_mech_df_in_prop(chn_name, nhcalc, rh, mech_df)

            print('{} calculation finished'.format(nhcalc))


    def update_spectra_mechanics_table(self, chn_name, nhcalc, rh, queue_id,qcm_queue, mech_queue):
        '''
        this function update data in tableWidget_spectra_mechanics_table 
        and relative information displaying
        '''
        # convert grho, drho and phi unit in mech_queue
        mech_queue = self.qcm.convert_mech_unit(mech_queue)
        # update current mech_key
        self.ui.label_spectra_mechanics_currmechkey.setText('Solution: {}; id: {}'.format(self.data_saver.get_mech_key(nhcalc, rh), queue_id))
        
        self.ui.label_spectra_mechanics_currmechkey.update()

        # clear table
        table = self.ui.tableWidget_spectra_mechanics_table
        table.clearContents()
        # get n of rows and columns of the table
        tb_rows = table.rowCount()
        tb_cols = table.columnCount()

        # get keys in qcm_queue and mech_queue
        qcm_cols = qcm_queue.columns
        mech_cols = mech_queue.columns

        # update table contents
        for tb_row in range(tb_rows):
            vh = table.verticalHeaderItem(tb_row).text()
            # print('vh', vh)
            # find corresponding key in qcm_queue or mech_queue
            for key, val in settings_init['mech_table_rowheaders'].items():
                if vh == val:
                    df_colname = key
                    # print(key)
                    if df_colname in qcm_cols:
                        df_queue = qcm_queue
                        # print(qcm_cols)
                    elif df_colname in mech_cols:
                        df_queue = mech_queue
                        # print(mech_cols)
                    else:
                        print('did not find', key, val)
                    break
                else:
                    # print(vh.encode('utf-8'))
                    # print(val.encode('utf-8'))
                    df_colname = ''
            if df_colname:
                row_data = df_queue[df_colname].iloc[0]
                for tb_col in range(tb_cols):
                    # print('r,c', tb_row, tb_col)
                    # if df_colname.endswith('s'): # multiple values
                    #     data = df_queue[df_colname].iloc[0][tb_col]
                    # else:
                    #     data = df_queue[df_colname].iloc[0]
                    if isinstance(row_data, list):
                        data = df_queue[df_colname].iloc[0][tb_col]
                    else:
                        data = row_data
                    # print(data)

                    tableitem = self.ui.tableWidget_spectra_mechanics_table.item(tb_row, tb_col)
                    if tableitem: # tableitem != 0
                        print('item not set')
                        tableitem.setText(str(data))
                    else: # item is not set
                        # print('item set')
                        self.ui.tableWidget_spectra_mechanics_table.setItem(tb_row, tb_col, QTableWidgetItem(str(data)))
        # print(self.ui.tableWidget_spectra_mechanics_table.item(0,0))
        self.ui.tableWidget_spectra_mechanics_table.viewport().update() # TODO update doesn't work. update in UI

        # TODO update contours if checked 


    def gen_nhcalc_str(self):
        '''
        generate nhcalc str from relative widgets
        spinBoxsettings_mechanics_nhcalc_n1/2/3
        '''
        n1 = self.settings['spinBoxsettings_mechanics_nhcalc_n1']
        n2 = self.settings['spinBoxsettings_mechanics_nhcalc_n2']
        n3 = self.settings['spinBoxsettings_mechanics_nhcalc_n3']
        return ''.join([n1, n2, n3])


    def gen_nhcalc_list(self):
        '''
        make list from nhcalc strs
        '''
        #TODO can be extanded to multiple strings
        return [self.gen_nhcalc_str()]


    def mechanics_plot_r_time(self):
        self.mechanics_plot('t')


    def mechanics_plot_r_temp(self):
        self.mechanics_plot('temp')


    def mechanics_plot_r1_r2(self):
        self.mechanics_plot('r1r2')

    def mechanics_plot_r2_r1(self):
        self.mechanics_plot('r2r1')


    def mechanics_plot(self, plot_type):
        '''
        make plot by plot_type
        variable is given by row selection of tableWidget_spectra_mechanics_table
        '''
        print('plot_type', plot_type)

        # get chn_name
        chn_name = self.mech_chn
        print('chn_name', chn_name)

        # get mech_key
        nhcalc = self.gen_nhcalc_str()
        print('nhcalc', nhcalc)
        
        rh =int(self.settings['comboBox_settings_mechanics_refG']) # rh can also be gotten from label_spectra_mechanics_currmechkey
        print('rh', rh)
        
        mech_key = self.data_saver.get_mech_key(nhcalc, rh)
        print('mech_key', mech_key)
        print('prop_chn_keys', getattr(self.data_saver, chn_name + '_prop').keys())

        # check if data exists mech_key
        if mech_key not in getattr(self.data_saver, chn_name + '_prop').keys(): # no corresponding prop data 
            return

        # get harmonics to plot
        plt_harms = [str(i) for i in range(1, settings_init['max_harmonic']+2, 2) if self.settings['checkBox_nhplot' + str(i)]]
        print('plt_harms', plt_harms)

        if not plt_harms: # no harmonic selected
            return

        # get variables to plot
        varplot = []
        selrowidx = self.ui.tableWidget_spectra_mechanics_table.selectionModel().selectedRows() # fully selected rows
        for idx in selrowidx:
            print(idx.row())
            vh = self.ui.tableWidget_spectra_mechanics_table.verticalHeaderItem(idx.row()).text()
            print(vh)
            for key, val in settings_init['mech_table_rowheaders'].items(): 
                if vh == val:
                    varplot.append(key)

        if not varplot: # no variable selected
            return
        
        # get data mode showall or marked
        # from tabWidget_settings
        if self.show_marked_data(): # show marked data only
            if self.data_saver.with_marks(chn_name):
                line_group = 'lm'
                mark = True
            else:
                line_group = 'l'
                mark = False
        else: # show all data
            mark = False
            line_group = 'l'

        if plot_type in ['t', 'temp']:
            if plot_type == 't':
                # get timeunit
                timeunit = self.settings['comboBox_timeunit']
                xdata = self.data_saver.get_t_marked_rows(chn_name, dropnanrow=False, unit=timeunit) # time
                xlabel = settings_init['data_plt_axis_label']['t'] # r'Time (unit)
                xlabel = self.time_str_unit_replace(xlabel) # replace unit by comboBox_timeunit

            elif plot_type == 'temp':
                # get tempunit
                tempunit = self.settings['comboBox_tempunit']
                xdata = self.data_saver.get_temp_by_uint_marked_rows(chn_name, dropnanrow=False, unit=tempunit) # temp
                xlabel = settings_init['data_plt_axis_label']['t'] # r'Time (unit)
                xlabel = self.temp_str_unit_replace(xlabel) # replace unit by comboBox_tempunit

            for var in varplot:
                ydata = self.data_saver.get_mech_column_to_columns_marked_rows(chn_name, mech_key, var, mark=mark, dropnanrow=False)
                ydata = self.qcm.convert_mech_unit(ydata) # convert unit for plot
                ylabel = settings_init['data_plt_axis_label'][var]
                if '_rh' in var: # variable referenced to rh
                    ylabel = ylabel.replace('{rh}', '{' + str(rh) + '}')
                
                ## make the plot
                # create figure
                self.prop_plot_list.append(
                    MatplotlibWidget(
                        parent=self.ui.scrollArea_data_mechanics_plots, 
                        axtype='prop',
                        showtoolbar=True,
                        xlabel=xlabel,
                        ylabel=ylabel,
                        title=mech_key,
                    )
                )
                
                # check if data is harmonic dependent
                if var.endswith('s'):
                    figharms = plt_harms
                else:
                    figharms = [str(rh)]
                # prepare data
                data_list = self.prepare_harm_data_for_mpl_update(chn_name, figharms, line_group, xdata, ydata, show_marked_when_all=False)
                
                # update data in figure
                self.prop_plot_list[-1].update_data(*data_list)
                # add to scrollarea
                self.update_mpl_to_prop_scrollarea()


        elif plot_type in ['r1r2', 'r2r1']:
            if len(varplot) < 2: # not enough variables selected
                print('Not enough rows are selected! Please select 2 rows.')
                return
            elif len(varplot) > 2: # too many variables selected
                print('Too many rows are selected! Please select 2 rows.')
                return
            
            if plot_type == 'r2r1': 
                varplot.reverse() # reverse varplot

            # varplot[0] as y
            ydata = self.data_saver.get_mech_column_to_columns_marked_rows(chn_name, mech_key, varplot[0], mark=mark, dropnanrow=False)
            ydata = self.qcm.convert_mech_unit(ydata) # convert unit for plot
            ylabel = settings_init['data_plt_axis_label'][varplot[0]]
            if '_rh' in varplot[0]: # variable referenced to rh
                ylabel = ylabel.replace('{rh}', '{' + str(rh) + '}')

            # varplot[1] as x
            xdata = self.data_saver.get_mech_column_to_columns_marked_rows(chn_name, mech_key, varplot[1], mark=mark, dropnanrow=False)
            xdata = self.qcm.convert_mech_unit(xdata) # convert unit for plot
            xlabel = settings_init['data_plt_axis_label'][varplot[1]]
            if '_rh' in varplot[1]: # variable referenced to rh
                xlabel = xlabel.replace('{rh}', '{' + str(rh) + '}')

            ## make the plot
            # create figure
            self.prop_plot_list.append(
                MatplotlibWidget(
                    parent=self.ui.scrollArea_data_mechanics_plots, 
                    axtype='prop',
                    showtoolbar=True,
                    xlabel=xlabel,
                    ylabel=ylabel,
                    title=mech_key,
                )
            )
            # check if data is harmonic dependent
            if varplot[0].endswith('s') or varplot[1].endswith('s'):
                figharms = plt_harms
            else:
                figharms = [str(rh)]
            # prepare data
            data_list = self.prepare_harm_data_for_mpl_update(chn_name, figharms, line_group, xdata, ydata, show_marked_when_all=False)
            
            # update data in figure
            self.prop_plot_list[-1].update_data(*data_list)
            # add to scrollarea
            self.update_mpl_to_prop_scrollarea()


    def update_mpl_to_prop_scrollarea(self):
        '''
        add mpl figure (prop_plot_list[-1]) into scrollArea_data_mechanics_plots
        at the end of its layout
        '''
        n = len(self.prop_plot_list)
        mpl = self.prop_plot_list[-1]

        self.ui.gridLayout_propplot.addWidget(mpl, (n-1)//2, (n-1)%2)
        if not (n-1)%2: # n is odd
            self.ui.gridLayout_propplot.setRowMinimumHeight((n-1)//2, settings_init['prop_plot_minmum_row_height'])
        # return
        # self.ui.scrollArea_data_mechanics_plots.setWidget(mpl)
        # self.ui.scrollArea_data_mechanics_plots.show()
        # return
        # layout = self.ui.scrollArea_data_mechanics_plots.layout()
        # layout.insertWidget(layout.count() - 1, mpl)


    def del_prop_plot(self):
        '''
        delete all prop plots in 
        '''
        for i in reversed(range(self.ui.gridLayout_propplot.count())):
            item = self.ui.gridLayout_propplot.itemAt(i)
            item.widget().deleteLater()
        self.prop_plot_list = []


    def on_clicked_set_temp_sensor(self, checked):
        # below only runs when vna is available
        if self.vna: # add not for testing code    
            if checked: # checkbox is checked
                # if not self.temp_sensor: # tempModule is not initialized 
                # get all tempsensor settings 
                tempmodule_name = self.settings['comboBox_tempmodule'] # get temp module

                thrmcpltype = self.settings['comboBox_thrmcpltype'] # get thermocouple type
                tempdevice = TempDevices.device_info(self.settings['comboBox_tempdevice']) #get temp device info

                # check senor availability
                package_str = settings_init['tempmodules_path'][2:].replace('/', '.') + tempmodule_name
                print(package_str)
                # import package
                temp_sensor = getattr(TempModules, tempmodule_name)

                try:
                    self.temp_sensor = temp_sensor(
                        tempdevice,
                        settings_init['tempdevices_dict'][tempdevice.product_type],
                        thrmcpltype,
                    )
                except Exception as e: # if failed return
                    print(e)
                    #TODO update in statusbar
                    return 

                # after tempModule loaded
                # # tempModule should take one arg 'thrmcpltype' and return temperature in C by calling tempModule.get_tempC
                try:
                    curr_temp = self.temp_sensor.get_tempC()

                    # save values to self.settings
                    self.settings['checkBox_control_rectemp'] = True
                    self.settings['checkBox_settings_temp_sensor'] = True
                    # set statusbar pushButton_status_temp_sensor text
                    self.statusbar_temp_update(curr_temp=curr_temp)
                    # disable items to keep the setting
                    self.disable_widgets(
                        'temp_settings_enable_disable_list'
                    )

                except Exception as e: # failed to get temperature from sensor
                    print(e)
                    # uncheck checkBoxes
                    self.ui.checkBox_control_rectemp.setChecked(False)
                    self.ui.checkBox_settings_temp_sensor.setChecked(False)
                    #TODO update in statusbar
            else: # is unchecked
                
                self.settings['checkBox_control_rectemp'] = False
                self.settings['checkBox_settings_temp_sensor'] = False

                # set statusbar pushButton_status_temp_sensor text
                self.statusbar_temp_update()
                
                # enable items to keep the setting
                self.enable_widgets(
                    'temp_settings_enable_disable_list'
                )
                # reset self.temp_sensor
                self.temp_sensor = None
                
                
            # update checkBox_settings_temp_sensor to self.settings
            # self.update_tempsensor()


    def statusbar_temp_update(self, curr_temp=None):

        # update statusbar temp sensor image
        if self.settings['checkBox_settings_temp_sensor']: # checked
            self.ui.pushButton_status_temp_sensor.setIcon(QIcon(":/icon/rc/temp_sensor.svg"))
            try:
            # get temp and change temp unit by self.settings['temp_unit_opts']
                if curr_temp is None:
                    curr_temp = self.temp_by_unit(self.temp_sensor.get_tempC())
                print(curr_temp)
                unit = settings_init['temp_unit_opts'].get(self.settings['comboBox_tempunit'])
                self.ui.pushButton_status_temp_sensor.setText('{:.1f} {}'.format(curr_temp, unit))
                self.ui.pushButton_status_temp_sensor.setIcon(QIcon(":/icon/rc/temp_sensor.svg"))
                self.ui.pushButton_status_temp_sensor.setToolTip('Temp. sensor is on.')
            except:
                #TODO update in statusbar
                pass
        else:
            self.ui.pushButton_status_temp_sensor.setIcon(QIcon(":/icon/rc/temp_sensor_off.svg"))
            self.ui.pushButton_status_temp_sensor.setText('')
            self.ui.pushButton_status_temp_sensor.setToolTip('Temp. sensor is off.')


        
    def on_clicked_checkBox_dynamicfitbyharm(self, value):
        self.ui.checkBox_dynamicfit.setEnabled(not value)


    def on_clicked_checkBox_fitfactorbyharm(self, value):
        self.ui.spinBox_fitfactor.setEnabled(not value)
        self.ui.label_fitfactor.setEnabled(not value)


    def set_stackedwidget_index(self, stwgt, idx=[], diret=[]):
        '''
        chenge the index of stwgt to given idx (if not []) 
        or to the given direction (if diret not [])
          diret=1: index += 1;
          diret=-1: index +=-1
        '''
        # print(self)
        if idx: # if index is not []
            stwgt.setCurrentIndex(idx) # set index to idx
        elif diret: # if diret is not []
            count = stwgt.count()  # get total pages
            current_index = stwgt.currentIndex()  # get current index
            stwgt.setCurrentIndex((current_index + diret) % count) # increase or decrease index by diret
    
    # update widget values in settings dict, only works with elements out of settings_settings
    
    def update_widget(self, signal):
        #  of the signal isA QLineEdit object, update QLineEdit vals in dict
        print('update', self.sender().objectName(), signal)
        print('type', type(signal))
        if isinstance(self.sender(), QLineEdit):
            # self.settings[self.sender().objectName()] = signal
            if UIModules.isint(signal): # is int
                self.settings[self.sender().objectName()] = int(signal)
            elif UIModules.isfloat(signal): # is float
                self.settings[self.sender().objectName()] = float(signal)
            else:
                self.settings[self.sender().objectName()] = signal
                
            # try:
            #     self.settings[self.sender().objectName()] = float(signal)
            # except:
            #     self.settings[self.sender().objectName()] = signal
        # if the sender of the signal isA QCheckBox object, update QCheckBox vals in dict
        elif isinstance(self.sender(), QCheckBox):
            self.settings[self.sender().objectName()] = signal
            # self.settings[self.sender().objectName()] = not self.settings[self.sender().objectName()]
        # if the sender of the signal isA QRadioButton object, update QRadioButton vals in dict
        elif isinstance(self.sender(), QRadioButton):
            self.settings[self.sender().objectName()] = signal
            # self.settings[self.sender().objectName()] = not self.settings[self.sender().objectName()]
        # if the sender of the signal isA QComboBox object, udpate QComboBox vals in dict
        elif isinstance(self.sender(), QComboBox):
            try: # if w/ userData, use userData
                value = self.sender().itemData(signal)
            except: # if w/o userData, use the text
                value = self.sender().itemText(signal)
            self.settings[self.sender().objectName()] = value
            print(self.settings[self.sender().objectName()])
        # if the sender of the signal isA QSpinBox object, udpate QComboBox vals in dict
        elif isinstance(self.sender(), QSpinBox):
            self.settings[self.sender().objectName()] = signal
        elif isinstance(self.sender(), QTabWidget):
            self.settings[self.sender().objectName()] = signal # index


    def update_harmwidget(self, signal):
        '''
        update widgets in treeWidget_settings_settings_harmtree
        except lineEdit_harmstart & lineEdit_harmend
        '''
        #  of the signal isA QLineEdit object, update QLineEdit vals in dict
        print('update', signal)
        harm = self.settings_harm

        if isinstance(self.sender(), QLineEdit):
                try:
                    self.set_harmdata(self.sender().objectName(), float(signal), harm=harm)
                except:
                    self.set_harmdata(self.sender().objectName(), 0, harm=harm)
        # if the sender of the signal isA QCheckBox object, update QCheckBox vals in dict
        elif isinstance(self.sender(), QCheckBox):
            self.set_harmdata(self.sender().objectName(), signal, harm=harm)
        # if the sender of the signal isA QRadioButton object, update QRadioButton vals in dict
        elif isinstance(self.sender(), QRadioButton):
            self.set_harmdata(self.sender().objectName(), signal, harm=harm)
        # if the sender of the signal isA QComboBox object, udpate QComboBox vals in dict
        elif isinstance(self.sender(), QComboBox):
            try: # if w/ userData, use userData
                value = self.sender().itemData(signal)
            except: # if w/o userData, use the text
                value = self.sender().itemText(signal)
            self.set_harmdata(self.sender().objectName(), value, harm=harm)
        # if the sender of the signal isA QSpinBox object, udpate QComboBox vals in dict
        elif isinstance(self.sender(), QSpinBox):
            self.set_harmdata(self.sender().objectName(), signal, harm=harm)

    def update_settings_chn(self):
        print('update_settings_chn')
        if self.sender().objectName() == 'tabWidget_settings_settings_samprefchn': # switched to samp
            idx = self.ui.tabWidget_settings_settings_samprefchn.currentIndex()
            
            print(idx)
            print(self.ui.pushButton_manual_refit.isChecked())
            print(idx < 2)
            print(self.ui.pushButton_manual_refit.isChecked() & (idx < 2))
            if self.ui.pushButton_manual_refit.isChecked() & (idx < 2): # current idx changed out of refit (2)
                print('samprefchn move out of 2')
                # disable refit widgets
                self.ui.pushButton_manual_refit.setChecked(False)
                self.init_manual_refit() # set the widgets


            if idx == 0: # swith to samp
                self.settings_chn = {
                    'name': 'samp', 
                    'chn': self.settings['comboBox_samp_channel']
                }
            elif idx == 1: # switched to ref
                self.settings_chn = {
                    'name': 'ref', 
                    'chn': self.settings['comboBox_ref_channel']
                }
            else: # refit
                print('refit chn')
                self.settings_chn = {
                    'name': 'refit', 
                    'chn': 0, # not available for test
                }

        elif self.sender().objectName() == 'comboBox_ref_channel' or 'comboBox_samp_channel': # define of samp/ref channel(s) changed
            # reset corrresponding ADC
            print(self.settings['comboBox_samp_channel'])
            print(self.settings['comboBox_ref_channel'])
            if self.settings_chn['name'] == 'samp':
                self.settings_chn['chn'] = self.settings['comboBox_samp_channel']
            elif self.settings_chn['name'] == 'ref':
                self.settings_chn['chn'] = self.settings['comboBox_ref_channel']
            print(self.settings_chn)


        # update treeWidget_settings_settings_harmtree
        self.update_harmonic_tab()

    def get_chn_by_name(self, name):
        '''
        get chn (str) by given name (str: 'samp' or 'ref')
        '''
        if name == 'samp':
            return  self.settings['comboBox_samp_channel']
        elif name == 'ref':
            return  self.settings['comboBox_ref_channel']

    def update_harmonic_tab(self):
        #print("update_harmonic_tab was called")
        harm = str(2 * self.ui.tabWidget_settings_settings_harm.currentIndex() + 1)
        self.settings_harm = harm
        
        self.update_frequencies()

        # update lineEdit_scan_harmsteps
        self.ui.lineEdit_scan_harmsteps.setText(
            str(self.get_harmdata('lineEdit_scan_harmsteps', harm=harm))
        )
        self.load_comboBox(self.ui.comboBox_tracking_method, 'span_mehtod_opts', harm=harm)
        self.load_comboBox(self.ui.comboBox_tracking_condition, 'span_track_opts', harm=harm)
        
        # update checkBox_harmfit
        self.ui.checkBox_harmfit.setChecked(
            self.get_harmdata('checkBox_harmfit', harm=harm)
        )

        # update spinBox_harmfitfactor
        self.ui.spinBox_harmfitfactor.setValue(
            self.get_harmdata('spinBox_harmfitfactor', harm=harm)
        )

        # update spinBox_peaks_num
        self.ui.spinBox_peaks_num.setValue(
            int(self.get_harmdata('spinBox_peaks_num', harm=harm))
        )

        # update radioButton_peaks_num_max
        self.ui.radioButton_peaks_num_max.setChecked(
            self.get_harmdata('radioButton_peaks_num_max', harm=harm)
        )

        # update radioButton_peaks_num_fixed
        self.ui.radioButton_peaks_num_fixed.setChecked(
            self.get_harmdata('radioButton_peaks_num_fixed', harm=harm)
        )

        # update radioButton_peaks_policy_minf
        self.ui.radioButton_peaks_policy_minf.setChecked(
            self.get_harmdata('radioButton_peaks_policy_minf', harm=harm)
        )


        # update radioButton_peaks_policy_maxamp
        self.ui.radioButton_peaks_policy_maxamp.setChecked(
            self.get_harmdata('radioButton_peaks_policy_maxamp', harm=harm)
        )

        # update lineEdit_peaks_threshold
        self.ui.lineEdit_peaks_threshold.setText(
            str(self.get_harmdata('lineEdit_peaks_threshold', harm=harm))
        )

        # update lineEdit_peaks_prominence
        self.ui.lineEdit_peaks_prominence.setText(
            str(self.get_harmdata('lineEdit_peaks_prominence', harm=harm))
        )

    def get_harmdata(self, objname, harm=None, chn_name=None):
        '''
        get data with given objname in 
        treeWidget_settings_settings_harmtree
        except lineEdit_harmstart & lineEdit_harmend
        '''
        if harm is None: # use harmonic displayed in UI
            harm = self.settings_harm
        if chn_name is None:
            chn_name = self.settings_chn['name']
        
        try:
            return self.settings['harmdata'][chn_name][str(harm)][objname]
        except:
            print(objname, 'is not found!')
            return None

    def set_harmdata(self, objname, val, harm=None, chn_name=None):
        '''
        set data with given objname in 
        treeWidget_settings_settings_harmtree
        except lineEdit_harmstart & lineEdit_harmend
        '''
        if harm is None: # use harmonic displayed in UI
            harm = self.settings_harm
        else: # use given harmonic. It is useful for mpl_sp<n> getting params
            pass
        if chn_name is None:
            chn_name = self.settings_chn['name']
        
        try:
            self.settings['harmdata'][chn_name][harm][objname] = val
        except:
            print(objname, 'is not found!')

    def update_base_freq(self, base_freq_index):
        self.settings['comboBox_base_frequency'] = self.ui.comboBox_base_frequency.itemData(base_freq_index) # in MHz
        print(self.settings['comboBox_base_frequency'])
        # update freq_range
        self.update_freq_range()
        # check freq_span
        self.check_freq_spans()
        # update freqrency display
        self.update_frequencies()
        # update statusbar
        self.statusbar_f0bw_update()

    def update_bandwidth(self, bandwidth_index):
        self.settings['comboBox_bandwidth'] = self.ui.comboBox_bandwidth.itemData(bandwidth_index) # in MHz
        print(self.settings['comboBox_bandwidth'])
        # update freq_range
        self.update_freq_range()
        # check freq_span
        self.check_freq_spans()
        # update freqrency display
        self.update_frequencies()
        # update statusbar
        self.statusbar_f0bw_update()

    def statusbar_f0bw_update(self):
        fbase = self.settings['comboBox_base_frequency']
        BW = self.settings['comboBox_bandwidth']
        self.ui.label_status_f0BW.setText('{}\u00B1{} MHz'.format(fbase, BW))
        self.ui.label_status_f0BW.setToolTip('base frequency = {} MHz; band width = {} MHz'.format(fbase, BW))

    def update_freq_range(self):
        '''
        update settings['freq_range'] (freq range allowed for scan)
        '''
        fbase = float(self.settings['comboBox_base_frequency']) * 1e6 # in Hz
        BW = float(self.settings['comboBox_bandwidth']) * 1e6 # in Hz
        freq_range = {}
        for harm in range(1, settings_init['max_harmonic']+2, 2):
            freq_range[str(harm)] = [harm*fbase-BW, harm*fbase+BW]
        self.settings['freq_range'] = freq_range
        print(self.settings['freq_range'])

    def get_freq_span(self, harm=None, chn_name=None):
        '''
        return freq_span of given harm and chn_name
        if harm and chn_name not given, use self.settings
        '''
        if harm is None:
            harm = self.settings_harm
        if chn_name is None:
            chn_name = self.settings_chn['name']

        return self.settings['freq_span'][chn_name][harm]

    def set_freq_span(self, span, harm=None, chn_name=None):
        '''
        set freq_span of given harm and chn_name
        if harm and chn_name not given, use self.settings
        span: ndarray of [f1, f2]
        '''
        if harm is None:
            harm = self.settings_harm
        if chn_name is None:
            chn_name = self.settings_chn['name']

        self.settings['freq_span'][chn_name][harm] = span

    def check_freq_spans(self):
        '''
        check if settings['freq_span'] (freq span for each harmonic) values in the allowed range self.settings['freq_range']
        '''
        if 'freq_span' in self.settings and self.settings['freq_span']:  # if self.settings['freq_span'] exist
            print('##################\n', self.settings['freq_span'])
            freq_span = {'samp': {}, 'ref': {}}
            for harm in range(1, settings_init['max_harmonic']+2, 2):
                harm = str(harm)  # convert from int to str
                freq_span['samp'][harm] = self.span_check(harm, *self.settings['freq_span']['samp'][harm])
                freq_span['ref'][harm] = self.span_check(harm, *self.settings['freq_span']['ref'][harm])

            self.settings['freq_span'] = freq_span
        else: # if self.settings['freq_span'] does not exist or is empty
            if 'freq_range' not in self.settings: # check if 
                self.update_freq_range() # initiate self.settings['freq_range']
            # set 'freq_span' == 'freq_range
            self.settings['freq_span']['samp'] = self.settings['freq_range']
            self.settings['freq_span']['ref'] = self.settings['freq_range']

    def update_frequencies(self):
        
        # get display mode (startstop or centerspan)
        disp_mode = self.settings['comboBox_settings_control_dispmode']
        # update lineEdit_startf<n> & lineEdit_endf<n>
        for harm in range(1, settings_init['max_harmonic']+2, 2):
            harm = str(harm)
            f1, f2 = np.array(self.settings['freq_span']['samp'][harm]) * 1e-6 # in MHz
            f1r, f2r = np.array(self.settings['freq_span']['ref'][harm]) * 1e-6 # in MHz
            if disp_mode == 'centerspan':
                # convert f1, f2 from start/stop to center/span
                f1, f2 = UIModules.converter_startstop_to_centerspan(f1, f2)
                f1r, f2r = UIModules.converter_startstop_to_centerspan(f1r, f2r)
            getattr(self.ui, 'lineEdit_startf' + harm).setText(UIModules.num2str(f1, precision=6)) # display as MHz
            getattr(self.ui, 'lineEdit_endf' + harm).setText(UIModules.num2str(f2, precision=6)) # display as MHz
            getattr(self.ui, 'lineEdit_startf' + harm + '_r').setText(UIModules.num2str(f1r, precision=6)) # display as MHz
            getattr(self.ui, 'lineEdit_endf' + harm + '_r').setText(UIModules.num2str(f2r, precision=6)) # display as MHz
                
        # update start/end in treeWidget_settings_settings_harmtree
        harm = self.settings_harm
        print(harm)
        f1, f2 = self.get_freq_span()
        # Set Start
        self.ui.lineEdit_scan_harmstart.setText(
            UIModules.num2str(f1*1e-6, precision=6)
        )
        # set End
        self.ui.lineEdit_scan_harmend.setText(
            UIModules.num2str(f2*1e-6, precision=6)
        )

    def update_freq_display_mode(self, signal):
        ''' update frequency dispaly in settings_control '''
        print(signal)
        disp_mode = self.settings['comboBox_settings_control_dispmode']
        # disp_mode = self.ui.comboBox_settings_control_dispmode.itemData(signal)

        # set label_settings_control_label1 & label_settings_control_label2
        if disp_mode == 'startstop':
            self.ui.label_settings_control_label1.setText('Start')
            self.ui.label_settings_control_label2.setText('End')
            self.ui.label_settings_control_label1_r.setText('Start')
            self.ui.label_settings_control_label2_r.setText('End')
        elif disp_mode == 'centerspan':
            self.ui.label_settings_control_label1.setText('Center')
            self.ui.label_settings_control_label2.setText('Span')
            self.ui.label_settings_control_label1_r.setText('Center')
            self.ui.label_settings_control_label2_r.setText('Span')
        
        self.update_frequencies()
            

    def on_editingfinished_harm_freq(self):
        '''
        update frequency when lineEdit_scan_harmstart or  lineEdit_scan_harmend edited
        '''
        # print(self.sender().objectName())
        harmstart = float(self.ui.lineEdit_scan_harmstart.text()) * 1e6 # in Hz
        harmend = float(self.ui.lineEdit_scan_harmend.text()) * 1e6 # in Hz
        harm=self.settings_harm
        print(harm, harmstart, harmend)
        f1, f2 = self.span_check(harm=harm, f1=harmstart, f2=harmend)
        print(f1, f2)
        self.set_freq_span([f1, f2])
        # self.settings['freq_span'][harm] = [harmstart, harmend] # in Hz
        # self.check_freq_spans()
        self.update_frequencies()


    def update_spanmethod(self, fitmethod_index):
        #NOTUSING
        value = self.ui.comboBox_tracking_method.itemData(fitmethod_index)
        self.set_harmdata('comboBox_tracking_method', value, harm=self.settings_harm)

    def update_spantrack(self, trackmethod_index):
        #NOTUSING
        value = self.ui.comboBox_tracking_condition.itemData(trackmethod_index)
        self.set_harmdata('comboBox_tracking_condition', value, harm=self.settings_harm)

    def update_harmfitfactor(self, harmfitfactor_index):
        #NOTUSING
        self.set_harmdata('comboBox_harmfitfactor', value, harm=self.settings_harm)

    def setvisible_samprefwidgets(self, samp_value=True, ref_value=False):
        '''
        set the visibility of sample and reference related widget
        '''
        print(samp_value)
        print(ref_value)
        self.setvisible_sampwidgets(value=samp_value)
        self.setvisible_refwidgets(value=ref_value)
        # set tabWidget_settings_settings_samprefchn
        if samp_value and ref_value: # both samp and ref channels are selected
            self.ui.tabWidget_settings_settings_samprefchn.setVisible(True)
            self.ui.tabWidget_settings_settings_samprefchn.setEnabled(True)
        elif not samp_value and not ref_value: # neither of samp or ref channel is selected
            self.ui.tabWidget_settings_settings_samprefchn.setVisible(False)
        else: # one of samp and ref channels is selected
            self.ui.tabWidget_settings_settings_samprefchn.setVisible(True)
            self.ui.tabWidget_settings_settings_samprefchn.setEnabled(False)
            if samp_value:
                self.ui.tabWidget_settings_settings_samprefchn.setCurrentIndex(0)
            else:
                self.ui.tabWidget_settings_settings_samprefchn.setCurrentIndex(1)







    def setvisible_sampwidgets(self, value=True):
        '''
        set the visibility of sample related widget
        '''
        self.ui.label_settings_control_samp.setVisible(value)
        self.ui.label_settings_control_label1.setVisible(value)
        self.ui.label_settings_control_label2.setVisible(value)
        for i in range(1, settings_init['max_harmonic']+2, 2):
            getattr(self.ui, 'lineEdit_startf' + str(i)).setVisible(value)
            getattr(self.ui, 'lineEdit_endf' + str(i)).setVisible(value)
        

    def setvisible_refwidgets(self, value=False):
        '''
        set the visibility of reference related widget
        '''
        self.ui.label_settings_control_ref.setVisible(value)
        self.ui.label_settings_control_label1_r.setVisible(value)
        self.ui.label_settings_control_label2_r.setVisible(value)
        for i in range(1, settings_init['max_harmonic']+2, 2):
            getattr(self.ui, 'lineEdit_startf' + str(i) + '_r').setVisible(value)
            getattr(self.ui, 'lineEdit_endf' + str(i) + '_r').setVisible(value)


    def update_vnachannel(self, index):
        '''
        update vna channels (sample and reference)
        if ref == sample: sender = 'none'
        '''
        sender_name = self.sender().objectName()
        print(sender_name)
        samp_channel = self.settings['comboBox_samp_channel']
        ref_channel = self.settings['comboBox_ref_channel']

        if ref_channel == samp_channel:
            # make sure sample and ref channels are not the same
            self.settings[sender_name] = 'none' # set the sender to 'none'
            #TODO update in statusbar
        # load_comboBox has to be used after the value saved in self.settings
        self.load_comboBox(getattr(self.ui, sender_name), 'vna_channel_opts')
        # set visibility of samp & ref related widgets
        self.setvisible_samprefwidgets(samp_value=self.settings['comboBox_samp_channel'] != 'none', ref_value=self.settings['comboBox_ref_channel'] != 'none')

    def update_tempsensor(self, signal):
        # NOTUSING
        print("update_tempsensor was called")
        self.settings['checkBox_settings_temp_sensor'] = signal
        # self.settings['checkBox_settings_temp_sensor'] = not self.settings['checkBox_settings_temp_sensor']


    def update_tempdevice(self, tempdevice_index):
        value = self.ui.comboBox_tempdevice.itemData(tempdevice_index)
        self.settings['comboBox_tempdevice'] = value
        # update display on label_temp_devthrmcpl
        self.set_label_temp_devthrmcpl()

    def update_thrmcpltype(self, thrmcpltype_index):
        value = self.ui.comboBox_thrmcpltype.itemData(thrmcpltype_index)
        self.settings['comboBox_thrmcpltype'] = value
        # update display on label_temp_devthrmcpl
        self.set_label_temp_devthrmcpl()

    def set_label_temp_devthrmcpl(self):
        '''
        display current selection of temp_sensor & thrmcpl
        in label_temp_devthrmcpl
        '''
        print(self.settings['comboBox_tempdevice'], self.settings['comboBox_thrmcpltype'])
        self.ui.label_temp_devthrmcpl.setText(
            'Dev/Thermocouple: {}/{}'.format(
                self.settings['comboBox_tempdevice'], 
                self.settings['comboBox_thrmcpltype']
            )
        )


    def update_timeunit(self, timeunit_index):
        value = self.ui.comboBox_timeunit.itemData(timeunit_index)
        self.settings['comboBox_timeunit'] = value
        #TODO update plt1 and plt2

    def update_tempunit(self, tempunit_index):
        value = self.ui.comboBox_tempunit.itemData(tempunit_index)
        self.settings['comboBox_tempunit'] = value
        #TODO update plt1 and plt2

    def update_timescale(self, timescale_index):
        value = self.ui.comboBox_xscale.itemData(timescale_index)
        self.settings['comboBox_xscale'] = value
        #TODO update plt1 and plt2

    def update_yscale(self, yscale_index):
        value = self.ui.comboBox_yscale.itemData(yscale_index)
        self.settings['comboBox_yscale'] = value
        #TODO update plt1 and plt2

    def update_linkx(self):
       self.settings['checkBox_linkx'] = not self.settings['checkBox_linkx']
        # TODO update plt1 and plt2


    def load_comboBox(self, comboBox, choose_dict_name, harm=None):
        '''
        load combobox value from self.settings 
        if harm == None
            set the value of combox from self.settings[comboBox]
        if harm = int
            the combobox is in harmwidget
        '''
        comboBoxName = comboBox.objectName()
        if settings_init[choose_dict_name]:
            for key in settings_init[choose_dict_name].keys():
                # TODO look for value from itemdata and loop use for in combox.count()
                if harm is None: # not embeded in subdict
                    if key == self.settings[comboBoxName]:
                        comboBox.setCurrentIndex(comboBox.findData(key))
                        break
                else:
                    if key == self.get_harmdata(comboBoxName, harm):
                        comboBox.setCurrentIndex(comboBox.findData(key))
                        break
                

    def update_guichecks(self, checkBox, name_in_settings):
        #NOTUSING
        print("update_guichecks was called")
        checkBox.setChecked(self.get_harmdata(name_in_settings, harm=self.settings_harm))


    # debug func
    def log_update(self):
        #NOTUSING
        with open('settings.json', 'w') as f:
            line = json.dumps(dict(self.settings), indent=4) + "\n"
            f.write(line)


    def load_normal_widgets(self, name_list):
        '''
        load those widgets don't require special setup
        find the type by widget's name
        '''
        for name in name_list:
            if name.startswith('lineEdit_'):
                getattr(self.ui, name).setText(self.settings[name])
            elif name.startswith('checkBox_') or name.startswith('radioButton_'):
                getattr(self.ui, name).setChecked(self.settings[name])




    def load_settings(self):
        '''
        setup the UI with the value from self.settings
        '''

        # load default crystal settings 

        # create self.settings['freq_range']. 
        # this has to be initated before any 
        self.update_freq_range()
        # update self.settings['freq_span']
        self.check_freq_spans()

        ## set default appearence
        # set window title
        self.setWindowTitle(_version.__projectname__ + ' Version ' + _version.__version__ )
        # set window size
        self.resize(*settings_init['window_size'])
        # set deflault displaying of tab_settings
        self.ui.tabWidget_settings.setCurrentIndex(0)
        # set deflault displaying of stackedWidget_spetratop
        self.ui.stackedWidget_spetratop.setCurrentIndex(0)
        # set deflault displaying of stackedWidget_spectra
        self.ui.stackedWidget_spectra.setCurrentIndex(0)
        # set deflault displaying of stackedWidget_data
        self.ui.stackedWidget_data.setCurrentIndex(0)
        # set deflault displaying of tabWidget_settings_settings_harm
        self.ui.tabWidget_settings_settings_harm.setCurrentIndex(0)
        # set deflault displaying of tabWidget_mechanics_chn
        self.ui.tabWidget_mechanics_chn.setCurrentIndex(0)
        # set actived harmonic tab
        # self.settings_harm = 1 #TODO
        # set active_chn
        self.ui.tabWidget_settings_settings_samprefchn.setCurrentIndex(0)
        # set progressbar
        self.updat_progressbar(val=0, text='')

        # set lineEdit_datafilestr
        self.ui.lineEdit_datafilestr.setText(self.data_saver.path)



        ## following data is read from self.settings
        # # hide harmonic related widgets which > max_disp_harmonic & < max_harmonic
        # for i in range(self.settings['max_disp_harmonic']+2, settings_init['max_harmonic']+2, 2):
        #     print(i)
        #     getattr(self.ui, 'checkBox_harm' +str(i)).setVisible(False)
        #     getattr(self.ui, 'lineEdit_startf' +str(i)).setVisible(False)
        #     getattr(self.ui, 'lineEdit_endf' +str(i)).setVisible(False)
        #     getattr(self.ui, 'lineEdit_startf' +str(i) + '_r').setVisible(False)
        #     getattr(self.ui, 'lineEdit_endf' +str(i) + '_r').setVisible(False)
        #     getattr(self.ui, 'tab_settings_settings_harm' +str(i)).setVisible(False)
        #     getattr(self.ui, 'checkBox_plt1_h' +str(i)).setVisible(False)
        #     getattr(self.ui, 'checkBox_plt2_h' +str(i)).setVisible(False)
        #     getattr(self.ui, 'tab_settings_data_harm_' +str(i)).setVisible(False)
        #     # more to be added here


        # load display_mode
        self.load_comboBox(self.ui.comboBox_settings_control_dispmode, 'display_opts')

        # load harm state
        for i in range(1, settings_init['max_harmonic']+2, 2):
            # settings/control/Harmonics
            getattr(self.ui, 'checkBox_harm' + str(i)).setChecked(self.settings['checkBox_harm' + str(i)])
            getattr(self.ui, 'checkBox_tree_harm' + str(i)).setChecked(self.settings['checkBox_harm' + str(i)])

        # store t0_shift in a temp variable to prevent it been overwritten while loading reference time 
        print(self.settings.keys())
        if 'dateTimeEdit_settings_data_t0shifted' in self.settings.keys(): # there is t0_shifted 
            temp = self.settings['dateTimeEdit_settings_data_t0shifted']
        else:
            temp = ''

        # load reference time
        if 'dateTimeEdit_reftime' in self.settings.keys(): # reference time has been defined
            print(self.settings['dateTimeEdit_reftime'])
            print(type(datetime.datetime.strptime(self.settings['dateTimeEdit_reftime'], settings_init['time_str_format'])))
            print(type(datetime.datetime.now()))
            # exit(0)
            self.ui.dateTimeEdit_reftime.setDateTime(datetime.datetime.strptime(self.settings['dateTimeEdit_reftime'], settings_init['time_str_format']))

        else: # reference time is not defined
            # use current time
            self.reset_reftime()

        # set t0_shifted back
        if temp:
            self.settings['dateTimeEdit_settings_data_t0shifted'] = temp

        # load default record interval
        self.ui.lineEdit_recordinterval.setText(str(self.settings['lineEdit_recordinterval']))
        # load default spectra refresh resolution
        self.ui.lineEdit_refreshresolution.setText(str(int(self.settings['lineEdit_refreshresolution'])))
        # update lineEdit_scaninterval
        self.set_lineEdit_scaninterval()

        # load default fitting and display options
        self.ui.checkBox_dynamicfit.setChecked(self.settings['checkBox_dynamicfit'])
        # load default fit factor range
        self.ui.spinBox_fitfactor.setValue(self.settings['spinBox_fitfactor'])
        # load default dynamicfitbyharm
        self.ui.checkBox_dynamicfitbyharm.setChecked(self.settings['checkBox_dynamicfitbyharm'])
        # load default fitfactorbyharm
        self.ui.checkBox_fitfactorbyharm.setChecked(self.settings['checkBox_fitfactorbyharm'])

        # load this first to create self.settings['freq_range'] & self.settings['freq_span']
        self.load_comboBox(self.ui.comboBox_base_frequency, 'base_frequency_opts')
        self.load_comboBox(self.ui.comboBox_bandwidth, 'bandwidth_opts')
        # update statusbar
        self.statusbar_f0bw_update()

        # create self.settings['freq_range']. 
        # this has to be initated before any 
        self.update_freq_range()
        # update self.settings['freq_span']
        self.check_freq_spans()
        # update frequencies display
        self.update_frequencies()

        # load default VNA settings
        self.load_comboBox(self.ui.comboBox_samp_channel, 'vna_channel_opts')
        self.load_comboBox(self.ui.comboBox_ref_channel, 'vna_channel_opts')
        
        # set treeWidget_settings_settings_harmtree display
        self.update_harmonic_tab()

        # load default temperature settings
        self.load_comboBox(self.ui.comboBox_settings_mechanics_selectmodel, 'thrmcpl_opts')

        self.ui.checkBox_settings_temp_sensor.setChecked(self.settings['checkBox_settings_temp_sensor'])

        self.load_comboBox(self.ui.comboBox_tempmodule, 'temp_class_opts_list')

        try:
            self.load_comboBox(self.ui.comboBox_tempdevice, 'tempdevs_opts')
        except:
            pass
        self.load_comboBox(self.ui.comboBox_thrmcpltype, 'thrmcpl_opts')
        # update display on label_temp_devthrmcpl
        self.set_label_temp_devthrmcpl() # this should be after temp_sensor & thrmcpl 

        # load default plots settings
        self.load_comboBox(self.ui.comboBox_timeunit, 'time_unit_opts')
        self.load_comboBox(self.ui.comboBox_tempunit, 'temp_unit_opts')
        self.load_comboBox(self.ui.comboBox_xscale, 'scale_opts')
        self.load_comboBox(self.ui.comboBox_yscale, 'scale_opts')

        self.ui.checkBox_linkx.setChecked(self.settings['checkBox_linkx'])

        # set default displaying of spectra show options
        self.ui.radioButton_spectra_showBp.setChecked(self.settings['radioButton_spectra_showBp'])
        self.ui.radioButton_spectra_showpolar.setChecked(self.settings['radioButton_spectra_showpolar'])
        self.ui.checkBox_spectra_showchi.setChecked(self.settings['checkBox_spectra_showchi'])

        # set data radioButton_data_showall
        self.ui.radioButton_data_showall.setChecked(self.settings['radioButton_data_showall'])
        self.ui.radioButton_data_showmarked.setChecked(self.settings['radioButton_data_showmarked'])

        # set default displaying of plot 1 options
        self.load_comboBox(self.ui.comboBox_plt1_optsy, 'data_plt_opts')
        self.load_comboBox(self.ui.comboBox_plt1_optsx, 'data_plt_opts')

        # set default displaying of plot 2 options
        self.load_comboBox(self.ui.comboBox_plt2_optsy, 'data_plt_opts')
        self.load_comboBox(self.ui.comboBox_plt2_optsx, 'data_plt_opts')

        # set checkBox_plt<1 and 2>_h<harm>
        for harm in range(1, settings_init['max_harmonic']+2, 2):
            getattr(self.ui, 'checkBox_plt1_h' + str(harm)).setChecked(self.settings['checkBox_plt1_h' + str(harm)])
            getattr(self.ui, 'checkBox_plt2_h' + str(harm)).setChecked(self.settings['checkBox_plt1_h' + str(harm)])

        # set radioButton_plt<n>_samp/ref
        self.ui.radioButton_plt1_samp.setChecked(self.settings['radioButton_plt1_samp'])
        self.ui.radioButton_plt1_ref.setChecked(self.settings['radioButton_plt1_ref'])
        self.ui.radioButton_plt2_samp.setChecked(self.settings['radioButton_plt2_samp'])
        self.ui.radioButton_plt2_ref.setChecked(self.settings['radioButton_plt2_ref'])


        # load t0_shifted time
        if 'dateTimeEdit_settings_data_t0shifted' in self.settings.keys(): # t0_shifted has been defined
            print(self.settings['dateTimeEdit_settings_data_t0shifted'])
            self.ui.dateTimeEdit_settings_data_t0shifted.setDateTime(datetime.datetime.strptime(self.settings['dateTimeEdit_settings_data_t0shifted'], settings_init['time_str_format']))

        else: # t0_shifted is not defined
            # use reference time
            self.ui.dateTimeEdit_settings_data_t0shifted.setDateTime(datetime.datetime.strptime(self.settings['dateTimeEdit_reftime'], settings_init['time_str_format']))

        # set widgets to display the channel reference setup
        # the value will be load from data_saver
        self.update_refsource()

        # update mpl_plt<n> at the end
        self.update_mpl_plt12()

        # settings_mechanics
        self.ui.checkBox_settings_mech_liveupdate.setChecked(self.settings['checkBox_settings_mech_liveupdate'])

        self.ui.checkBox_nhplot1.setChecked(self.settings['checkBox_nhplot1'])
        self.ui.checkBox_nhplot3.setChecked(self.settings['checkBox_nhplot3'])
        self.ui.checkBox_nhplot5.setChecked(self.settings['checkBox_nhplot5'])
        self.ui.checkBox_nhplot7.setChecked(self.settings['checkBox_nhplot7'])
        self.ui.checkBox_nhplot9.setChecked(self.settings['checkBox_nhplot9'])

        self.ui.spinBox_settings_mechanics_nhcalc_n1.setValue(self.settings['spinBox_settings_mechanics_nhcalc_n1'])
        self.ui.spinBox_settings_mechanics_nhcalc_n2.setValue(self.settings['spinBox_settings_mechanics_nhcalc_n2'])
        self.ui.spinBox_settings_mechanics_nhcalc_n3.setValue(self.settings['spinBox_settings_mechanics_nhcalc_n3'])

        self.ui.comboBox_settings_mechanics_refG.setCurrentIndex(self.ui.comboBox_settings_mechanics_refG.findData(self.settings['comboBox_settings_mechanics_refG']))

        self.ui.checkBox_settings_mechanics_witherror.setChecked(self.settings['checkBox_settings_mechanics_witherror'])

        self.load_comboBox(self.ui.comboBox_settings_mechanics_selectmodel, 'qcm_model_opts')

    def update_refsource(self):
        '''
        update widgets related to reference source
        '''
        print('ref_channel_opts')
        print(self.settings['comboBox_settings_data_samprefsource'])
        self.load_comboBox(self.ui.comboBox_settings_data_samprefsource, 'ref_channel_opts')
        self.load_comboBox(self.ui.comboBox_settings_data_refrefsource, 'ref_channel_opts')
        self.ui.lineEdit_settings_data_samprefidx.setText(str(self.settings['lineEdit_settings_data_samprefidx']))
        self.ui.lineEdit_settings_data_refrefidx.setText(str(self.settings['lineEdit_settings_data_refrefidx']))

    def load_refsource(self):
        '''
        update widgets related to reference source
        '''
        print('ref_channel_opts')
        self.settings['comboBox_settings_data_samprefsource'] = self.data_saver.exp_ref['samp_ref'][0]
        self.settings['comboBox_settings_data_refrefsource'] = self.data_saver.exp_ref['ref_ref'][0]

        self.settings['lineEdit_settings_data_samprefidx'] = self.data_saver.exp_ref['samp_ref'][1]
        self.settings['lineEdit_settings_data_refrefidx'] = self.data_saver.exp_ref['ref_ref'][1]


    def check_freq_range(self, harmonic, min_range, max_range):
        #NOTUSING
        startname = 'lineEdit_startf' + str(harmonic)
        endname = 'lineEdit_endf' + str(harmonic)
        # check start frequency range
        if float(self.settings[startname]) <= min_range or float(self.settings[startname]) >= max_range:
            print('ERROR')
            self.settings[startname] = float(min_range)
        if float(self.settings[startname]) >= float(self.settings[endname]):
            if float(self.settings[startname]) == float(self.settings[endname]):
                print('The start frequency cannot be the same as the end frequency!')
                self.settings[startname] = min_range
                # self.settings[endname] = max_range
            else:
                print('The start frequency is greater than the end frequency!')
                self.settings[startname] = min_range
        # check end frequency range
        if float(self.settings[endname]) <= min_range or float(self.settings[endname]) >= max_range:
            print('ERROR')
            self.settings[endname] = max_range
        if float(self.settings[endname]) <= float(self.settings[startname]):
            print('ERROR: The end frequency is less than the start frequency!')
            if float(self.settings[startname]) == max_range:
                print('The start frequency cannot be the same as the end frequency!')
                self.settings[startname] = min_range
                # self.settings[endname] = max_range - 0.9
            else:
                self.settings[endname] = max_range

    def smart_peak_tracker(self, harmonic=None, freq=None, conductance=None, susceptance=None, G_parameters=None):
        # NOT USING
        self.peak_tracker.f0 = G_parameters[0]
        self.peak_tracker.g0 = G_parameters[1]

        track_condition = self.get_harmdata('comboBox_tracking_condition', harmonic) 
        track_method = self.get_harmdata('comboBox_tracking_method', harmonic)
        chn = self.active_chn['name']
        # determine the structure field that should be used to extract out the initial-guessing method
        if track_method == 'bmax':
            resonance = susceptance
        else:
            resonance = conductance
        index = GBFitting.findpeaks(resonance, output='indices', sortstr='descend')
        cen = freq[index[0]] # peak center
        # determine the estimated associated conductance (or susceptance) value at the resonance peak
        Gmax = resonance[index[0]] 
        # determine the estimated half-max conductance (or susceptance) of the resonance peak
        half_amp = (Gmax-np.amin(resonance))/2 + np.amin(resonance) 
        half_wid = np.absolute(freq[np.where(np.abs(half_amp-resonance)==np.min(np.abs(half_amp-resonance)))[0][0]] -  cen)
        current_xlim = self.get_freq_span(harm=harmonic, chn=chn)
        # get the current center and current span of the data in Hz
        current_center, current_span = UIModules.converter_startstop_to_centerspan(current_xlim[0], current_xlim[1])
        # find the starting and ending frequency of only the peak in Hz
        if track_condition == 'fixspan':
            if np.absolute(np.mean(np.array([freq[0],freq[-1]]))-cen) > 0.1 * current_span:
                # new start and end frequencies in Hz
                new_xlim=np.array([cen-0.5*current_span,cen+0.5*current_span])
        elif track_condition == 'fixcenter':
            # peak_xlim = np.array([cen-half_wid*3, cen+half_wid*3])
            if np.sum(np.absolute(np.subtract(current_xlim, np.array([current_center-3*half_wid, current_center + 3*half_wid])))) > 3e3:
                #TODO above should equal to abs(sp - 6 * half_wid) > 3e3
                # set new start and end freq based on the location of the peak in Hz
                new_xlim = np.array(current_center-3*half_wid, current_center+3*half_wid)

        elif track_condition == 'auto':
            # adjust window if neither span or center is fixed (default)
            if(np.mean(current_xlim)-cen) > 1*current_span/12:
                new_xlim = current_xlim - current_span / 15  # new start and end frequencies in Hz
            elif (np.mean(current_xlim)-cen) < -1*current_span/12:
                new_xlim = current_xlim + current_span / 15  # new start and end frequencies in Hz
            else:
                thresh1 = .05 * current_span + current_xlim[0] # Threshold frequency in Hz
                thresh2 = .03 * current_span # Threshold frequency span in Hz
                LB_peak = cen - half_wid * 3 # lower bound of the resonance peak
                if LB_peak - thresh1 > half_wid * 8: # if peak is too thin, zoom into the peak
                    new_xlim[0] = (current_xlim[0] + thresh2) # Hz
                    new_xlim[1] = (current_xlim[1] - thresh2) # Hz
                elif thresh1 - LB_peak > -half_wid*5: # if the peak is too fat, zoom out of the peak
                    new_xlim[0] = current_xlim[0] - thresh2 # Hz
                    new_xlim[1] = current_xlim[1] + thresh2 # Hz
        elif track_condition == 'fixcntspn':
            # bothe span and cent are fixed
            # no changes
            return
        elif track_condition == 'usrdef': #run custom tracking algorithm
            ### CUSTOM, USER-DEFINED
            ### CUSTOM, USER-DEFINED
            ### CUSTOM, USER-DEFINED
            return

        # set new start/end freq in Hz
        self.set_freq_span(new_xlim, harm= harmonic, chn=chn)
        self.check_freq_spans()
        self.update_frequencies()
    
    def read_scan(self, harmonic):
        #NOTUSING
        # read in live data scans
        if self.peak_tracker.refit_flag == 0:
            flag = 0
            rawdata = np.array([])
            start1 = self.settings['lineEdit_startf' + str(harmonic)]
            end1 = self.settings['lineEdit_endf' + str(harmonic)]
            if harmonic < 11:
                rawfile = 'myVNAdata0' + str(harmonic) + '.csv'
            else:
                rawfile = 'myVNAdata11.csv'
            while flag == 0:
                with open(rawfile, newline='') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        np.append(rawdata, row[0])
                num_pts = self.get_harmdata('lineEdit_scan_harmsteps', harm=self.settings_harm)
                if len(rawdata) == num_pts*2:
                    self.Peak_tracker.G = 1e3 * rawdata[:num_pts+1]
                    self.peak_tracker.B = 1e3 * rawdata[num_pts:]
                    self.peak_tracker.f = np.arange(start1,end1-(end1-start1)/num_pts+1,(end1-start1)/num_pts)
                    flag = 1
                    print('Status: Scan successful.')
        #TODO refit loaded raw spectra data
        else:
            pass

    def updat_progressbar(self, val=0, text=''):
        '''
        update progressBar_status_interval_time
        '''
        self.ui.progressBar_status_interval_time.setValue(val)
        self.ui.progressBar_status_interval_time.setFormat(text)

    def data_collection(self):
        '''
        data collecting routine
        '''
        self.idle = False
        # self.timer.setSingleShot(True)
        scan_interval = self.settings['lineEdit_scaninterval'] * 1000 # in ms

        # update the interval of timer
        self.timer.setInterval(scan_interval)

        # update the bartimer set up
        bar_interval = scan_interval / settings_init['progressbar_update_steps']
        if bar_interval < settings_init['progressbar_min_interval']: # interval is to small
            bar_interval = settings_init['progressbar_min_interval']
        elif bar_interval > settings_init['progressbar_min_interval']: # interval is to big
            bar_interval = settings_init['progressbar_max_interval']

        print(scan_interval)
        print(bar_interval)

        self.bartimer.setInterval(bar_interval)
        self.bartimer.start()

        ## start to read data
        # set channels to collect data
        chn_name_list = []
        print(chn_name_list)

        # only one channel can be 'none'
        if self.settings['comboBox_samp_channel'] != 'none': # sample channel is not selected
            chn_name_list.append('samp')
        if self.settings['comboBox_ref_channel'] != 'none': # reference channel is not selected
            chn_name_list.append('ref')

        harm_list = [str(i) for i in range(1, settings_init['max_harmonic']+2, 2) if self.settings['checkBox_harm' + str(i)]] # get all checked harmonic into a list

        print(self.settings['comboBox_samp_channel'])
        print(self.settings['comboBox_ref_channel'])
        print(chn_name_list)
        print(harm_list)

        f, G, B = {}, {}, {}
        fs = {} # peak centers
        gs = {} # dissipations hwhm 
        curr_time = {}
        curr_temp = {}
        marks = [0 for _ in harm_list] # 'samp' and 'ref' chn test the same harmonics
        for chn_name in chn_name_list:
            # scan harmonics (1, 3, 5...)
            f[chn_name], G[chn_name], B[chn_name] = {}, {}, {}
            fs[chn_name] = []
            gs[chn_name] = []
            curr_temp[chn_name] = None

            self.reading = True
            # read time
            curr_time[chn_name] = datetime.datetime.now().strftime(settings_init['time_str_format'])
            print(curr_time)

            # read temp if checked 
            if self.settings['checkBox_settings_temp_sensor'] == True: # record temperature data
                curr_temp[chn_name] = self.temp_sensor.get_tempC()
                # update status bar
                self.statusbar_temp_update(curr_temp=curr_temp[chn_name])

            with self.vna:
                # data collecting and plot
                for harm in harm_list:
                    # get data
                    print(harm_list)
                    f[chn_name][harm], G[chn_name][harm], B[chn_name][harm] = self.get_vna_data_no_with(harm=harm, chn_name=chn_name)
                    
                    # put f, G, B to peak_tracker for later fitting and/or tracking
                    self.peak_tracker.update_input(chn_name, harm, f[chn_name][harm], G[chn_name][harm], B[chn_name][harm], self.settings['harmdata'], self.settings['freq_span'])

                    # plot data in sp<harm>
                    if self.settings['radioButton_spectra_showGp']: # checked
                        getattr(self.ui, 'mpl_sp' + str(harm)).update_data(('lG', f[chn_name][harm], G[chn_name][harm]))
                    elif self.settings['radioButton_spectra_showBp']: # checked
                        getattr(self.ui, 'mpl_sp' + str(harm)).update_data(('lG', f[chn_name][harm], G[chn_name][harm]), ('lB', f[chn_name][harm], B[chn_name][harm]))
                    elif self.settings['radioButton_spectra_showpolar']: # checked
                        getattr(self.ui, 'mpl_sp' + str(harm)).update_data(('lP', G[chn_name][harm], B[chn_name][harm]))

            # set xticks
            # self.mpl_set_faxis(getattr(self.ui, 'mpl_sp' + str(harm)).ax[0])
            
            self.reading = False
                
            # fitting and tracking
            for harm in harm_list:
                if self.get_harmdata('checkBox_harmfit', harm=harm, chn_name=chn_name): # checked to fit

                    fit_result = self.peak_tracker.peak_fit(chn_name, harm, components=False)
                    print(fit_result)
                    print(fit_result['v_fit'])
                    # print(fit_result['comp_g'])

                    # plot fitted data
                    if self.settings['radioButton_spectra_showGp']: # checked
                        getattr(self.ui, 'mpl_sp' + harm).update_data(('lGfit',f[chn_name][harm], fit_result['fit_g']))
                    elif self.settings['radioButton_spectra_showBp']: # checked
                        getattr(self.ui, 'mpl_sp' + harm).update_data(('lGfit',f[chn_name][harm], fit_result['fit_g']), ('lBfit',f[chn_name][harm], fit_result['fit_b']))
                    elif self.settings['radioButton_spectra_showpolar']: # checked
                        getattr(self.ui, 'mpl_sp' + harm).update_data(('lPfit', fit_result['fit_g'], fit_result['fit_b']))


                    # update lsp
                    factor_span = self.peak_tracker.get_output(key='factor_span', chn_name=chn_name, harm=harm)
                    gc_list = [fit_result['v_fit']['g_c']['value']] * 2 # make its len() == 2
                    bc_list = [fit_result['v_fit']['b_c']['value']] * 2 # make its len() == 2

                    print(factor_span)
                    print(gc_list)
                    if self.settings['radioButton_spectra_showGp'] or self.settings['radioButton_spectra_showBp']: # show G or GB

                        getattr(self.ui, 'mpl_sp' + harm).update_data(('lsp', factor_span, gc_list))
                    elif self.settings['radioButton_spectra_showpolar']: # polar plot
                        idx = np.where((f[chn_name][harm] >= factor_span[0]) & (f[chn_name][harm] <= factor_span[1]))

                        getattr(self.ui, 'mpl_sp' + harm).update_data(('lsp', fit_result['fit_g'][idx], fit_result['fit_b'][idx]))


                    # update srec
                    cen_rec_freq = fit_result['v_fit']['cen_rec']['value']
                    cen_rec_G = self.peak_tracker.get_output(key='gmod', chn_name=chn_name, harm=harm).eval(
                        self.peak_tracker.get_output(key='params', chn_name=chn_name, harm=harm),
                        x=cen_rec_freq
                    ) 
                    
                    # save data to fs and gs
                    fs[chn_name].append(fit_result['v_fit']['cen_rec']['value']) # fs 
                    gs[chn_name].append(fit_result['v_fit']['wid_rec']['value'] ) # gs = half_width 
                    print(cen_rec_freq)
                    print(cen_rec_G)

                    if self.settings['radioButton_spectra_showGp'] or self.settings['radioButton_spectra_showBp']: # show G or GB
                        getattr(self.ui, 'mpl_sp' + harm).update_data(('srec', cen_rec_freq, cen_rec_G))
                    elif self.settings['radioButton_spectra_showpolar']: # polar plot
                        cen_rec_B = self.peak_tracker.get_output(key='bmod', chn_name=chn_name, harm=harm).eval(
                            self.peak_tracker.get_output(key='params', chn_name=chn_name, harm=harm),
                            x=cen_rec_freq
                        )                        

                        getattr(self.ui, 'mpl_sp' + harm).update_data(('srec', cen_rec_G, cen_rec_B))
                    
                    if self.settings['checkBox_spectra_showchi']: # show chi square
                        getattr(self.ui, 'mpl_sp' + harm).update_sp_text_chi(fit_result['v_fit']['chisqr'])


                ## get tracking data
                # get span from tracking
                span, cen_trk_freq = self.peak_tracker.peak_track(chn_name=chn_name, harm=harm)
                # check span range is in range
                span = self.span_check(harm, *span)
                # save span 
                self.set_freq_span(span, harm=harm, chn_name=chn_name)
                # update UI
                self.update_frequencies()
                
                # update strk
                cen_trk_G = G[chn_name][harm][
                    np.argmin(np.abs(f[chn_name][harm] - cen_trk_freq))
                    ]

                print(cen_trk_freq)
                print(cen_trk_G)

                
                if self.settings['radioButton_spectra_showGp'] or self.settings['radioButton_spectra_showBp']: # show G or GB
                    getattr(self.ui, 'mpl_sp' + harm).update_data(('strk', cen_trk_freq, cen_trk_G))
                elif self.settings['radioButton_spectra_showpolar']: # polar plot
                    cen_trk_B = B[chn_name][harm][
                    np.argmin(np.abs(f[chn_name][harm] - cen_trk_freq))
                    ]                        

                    getattr(self.ui, 'mpl_sp' + harm).update_data(('strk', cen_trk_G, cen_trk_B))

                # set xticks
                # self.mpl_set_faxis(getattr(self.ui, 'mpl_sp' + str(harm)).ax[0])
        

        # Save scan data to file fitting data in RAM to file
        if int(self.counter) % int(self.settings['lineEdit_refreshresolution']) == 0: # check if to save by intervals
            self.writing = True
            self.data_saver.dynamic_save(chn_name_list, harm_list, t=curr_time, temp=curr_temp, f=f, G=G, B=B, fs=fs, gs=gs, marks=marks)
        
            # plot data
            self.update_mpl_plt12()

        # increase counter
        self.counter += 1

        if not self.timer.isActive(): # if timer is stopped
            # save data
            self.process_saving_when_stop()

        self.writing = False

        # display total points collected 
        self.set_status_pts()


        self.idle = True


        self.writing = True
        # save scans to file

        self.writing = False

        # 
        # wait bar


    def data_refit(self, chn_name, sel_idx_dict):
        '''
        data refit routine
        sel_idx_dict = {
            'harm': [idx]
        }
        '''
        if self.idle == False:
            print('Data collection is running!')
            return

        ## start to read data from data saver
        # set channels to collect data

        print('sel_idx_dict\n', sel_idx_dict)
        # reform dict
        sel_harm_dict = UIModules.idx_dict_to_harm_dict(sel_idx_dict)
        queue_list = sel_harm_dict.keys()
        print('sel_harm_dict\n', sel_harm_dict)

        for queue_id in queue_list:
            # initiate data of queue_id

            # scan harmonics (1, 3, 5...)
            fs = []
            gs = []

            self.reading = True

            # data reading and plot
            harm_list = sel_harm_dict[queue_id]
            for harm in harm_list:
                # get data
                f, G, B = self.data_saver.get_raw(chn_name, queue_id, harm)
                print(len(f), len(G), len(B))
                
                # put f, G, B to peak_tracker for later fitting and/or tracking
                self.peak_tracker.update_input(chn_name, harm, f, G, B, self.settings['harmdata'], []) # freq_span set to [], since we don't need to track the peak 

                # fitting
                fit_result = self.peak_tracker.peak_fit(chn_name, harm, components=False)
                print(fit_result)
                print(fit_result['v_fit'])
                # print(fit_result['comp_g'])

                # save data to fs and gs
                fs.append(fit_result['v_fit']['cen_rec']['value']) # fs 
                gs.append(fit_result['v_fit']['wid_rec']['value'] ) # gs = half_width 

                # update lsp
                factor_span = self.peak_tracker.get_output(key='factor_span', chn_name=chn_name, harm=harm)
                gc_list = [fit_result['v_fit']['g_c']['value']] * 2 # make its len() == 2
                bc_list = [fit_result['v_fit']['b_c']['value']] * 2 # make its len() == 2
                print(factor_span)
                print(gc_list)

                # update srec
                cen_rec_freq = fit_result['v_fit']['cen_rec']['value']
                cen_rec_G = self.peak_tracker.get_output(key='gmod', chn_name=chn_name, harm=harm).eval(
                    self.peak_tracker.get_output(key='params', chn_name=chn_name, harm=harm),
                    x=cen_rec_freq
                ) 
                print(cen_rec_freq)
                print(cen_rec_G)
                
                # plot data in sp<harm> and fitting
                if self.settings['radioButton_spectra_showGp']: # checked
                    getattr(self.ui, 'mpl_sp' + harm).update_data(
                        ('lG', f, G), 
                        ('lGfit',f, fit_result['fit_g']),
                        ('lsp', factor_span, gc_list),
                        ('srec', cen_rec_freq, cen_rec_G)
                    )
                elif self.settings['radioButton_spectra_showBp']: # checked
                    getattr(self.ui, 'mpl_sp' + harm).update_data(
                        ('lG', f, G), 
                        ('lB', f, B),
                        ('lGfit',f, fit_result['fit_g']),
                        ('lBfit',f, fit_result['fit_b']), 
                        ('lsp', factor_span, gc_list),
                        ('srec', cen_rec_freq, cen_rec_G),
                    )
                elif self.settings['radioButton_spectra_showpolar']: # checked
                    idx = np.where(f >= factor_span[0] & f <= factor_span[1])

                    cen_rec_B = self.peak_tracker.get_output(key='bmod', chn_name=chn_name, harm=harm).eval(
                        self.peak_tracker.get_output(key='params', chn_name=chn_name, harm=harm),
                        x=cen_rec_freq
                    )     

                    getattr(self.ui, 'mpl_sp' + harm).update_data(('lP', G, B),
                        ('lPfit', fit_result['fit_g'], fit_result['fit_b']),
                        ('lsp', fit_result['fit_g'][idx], fit_result['fit_b'][idx]),
                        ('srec', cen_rec_G, cen_rec_B),
                    )

                if self.settings['checkBox_spectra_showchi']: # show chi square
                    getattr(self.ui, 'mpl_sp' + harm).update_sp_text_chi(fit_result['v_fit']['chisqr'])
            
            self.reading = False

            # save scan data to file fitting data in data_saver 
            self.data_saver.update_refit_data(chn_name, queue_id, harm_list, fs=fs, gs=gs)
        
            # plot data
            self.update_mpl_plt12()
                




    def get_all_checked_harms(self):
        '''
        return all checked harmonics in a list of str
        '''
        return [str(i) for i in range(1, settings_init['max_harmonic']+2, 2) if 
        self.settings['checkBox_harm' + str(i)]] # get all checked harmonics
    
    def update_progressbar(self):
        '''
        update progressBar_status_interval_time
        '''

        # read reainingTime from self.timer
        timer_remain = self.timer.remainingTime() / 1000 # in s
        timer_interval = self.timer.interval() / 1000 # in s
        # print(timer_remain)
        # print(timer_interval)
        # print(min(round((1 - timer_remain / timer_interval) * 100), 100))
        self.updat_progressbar(
            val=min(round((1 - timer_remain / timer_interval) * 100), 100), 
            text='{:.1f} s'.format(timer_remain)
        )





#endregion



if __name__ == '__main__':
    import sys

    app = QApplication(sys.argv)
    qcm_app = QCMApp()
    qcm_app.show()
    sys.exit(app.exec_())

