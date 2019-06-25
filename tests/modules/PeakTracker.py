'''
class for peak tracking and fitting 
'''
import numpy as np
from lmfit import Model, Minimizer, minimize, Parameters, fit_report, printfuncs
from lmfit.models import ConstantModel
from scipy.signal import find_peaks, find_peaks_cwt, peak_widths, peak_prominences
from random import randrange

from UISettings import settings_init
from modules import UIModules

# for debugging
import traceback

# peak_min_distance_Hz = 1e3 # in Hz
# peak_min_width_Hz = 10 # in Hz full width
# xtol = 1e-18 
# ftol = 1e-18

# peak finder method
# peak_finder_method = 'simple_func'
peak_finder_method = 'py_func'

def fun_G(x, amp, cen, wid, phi):
    ''' 
    function of relation between frequency (f) and conductance (G) 
    '''
    return amp * (4 * wid**2 * x**2 * np.cos(phi) - 2 * wid * x * np.sin(phi) * (cen**2 - x**2)) / (4 * wid**2 * x**2 + (cen**2 -x**2)**2)


def fun_B(x, amp, cen, wid, phi):
    ''' 
    function of relation between frequency (f) and susceptance (B) 
    '''
    return amp * (4 * wid**2 * x**2 * np.sin(phi) + 2 * wid * x * np.cos(phi) * (cen**2 - x**2)) / (4 * wid**2 * x**2 + (cen**2 -x**2)**2)


def make_gmod(n):
    '''
    make complex model of G (w/o params) for multiple (n) peaks
    input:
    n:    number of peaks
    '''
    gmod = ConstantModel(prefix='g_')
    for i in np.arange(n):
        gmod_i = Model(fun_G, prefix='p'+str(i)+'_', name='g'+str(i))
        gmod += gmod_i
    return gmod


def make_bmod(n):
    '''
    make complex model of B (w/o params) for multiple (n) peaks
    input:
    n:    number of peaks
    '''
    bmod = ConstantModel(prefix='g_')
    for i in np.arange(n):
        bmod_i = Model(fun_B, prefix='p'+str(i)+'_', name='b'+str(i))
        bmod += bmod_i
    return bmod


def make_gbmodel(n=1):
    '''
    make complex model for multiple peaks
    input:
    n:    number of peaks
    '''
    gmod = ConstantModel(prefix='g_')
    bmod = ConstantModel(prefix='b_')

    for i in np.arange(n):
        # gmod and bmod sharing the same varible so use the same prefix
        gmod_i = Model(fun_G, prefix='p'+str(i)+'_', name='g'+str(i))
        bmod_i = Model(fun_B, prefix='p'+str(i)+'_', name='b'+str(i))
        gmod += gmod_i
        bmod += bmod_i
    
    return gmod, bmod


def make_models(n=1):
    '''
    Since minimizeResult class doesn't have eval_components method, we will make complex models with single peak for evaluation
    input:
        n:    number of peaks
    output:
        gmods = list of n models of G
        bmods = list of n models of B
    '''
    gmods = []
    bmods = []
    gc = ConstantModel(prefix='g_')
    bc = ConstantModel(prefix='b_')

    for i in np.arange(n):
        # gmod and bmod sharing the same varible so use the same prefix
        gmod_i = Model(fun_G, prefix='p'+str(i)+'_', name='g'+str(i)) + gc
        bmod_i = Model(fun_B, prefix='p'+str(i)+'_', name='b'+str(i)) + bc
        gmods.append(gmod_i)
        bmods.append(bmod_i)
    
    return gmods, bmods


def make_model_n(n=1):
    '''
    Since minimizeResult class doesn't have eval_components method, we will make complex models with single peak for evaluation
    input:
        n:    the nth peak
    output:
        gmod = the nth model of G
        bmod = the nth model of B
    '''
    gc = ConstantModel(prefix='g_')
    bc = ConstantModel(prefix='b_')

    # gmod and bmod sharing the same varible so use the same prefix
    gmod = Model(fun_G, prefix='p'+str(i)+'_', name='g'+str(i)) + gc
    bmod = Model(fun_B, prefix='p'+str(i)+'_', name='b'+str(i)) + bc
    
    return gmod, bmod


def make_models_pars(n=1):
    '''
    make complex model for multiple peaks
    input:
    n:    number of peaks
    '''
    gmod = ConstantModel(prefix='g_', name='cg')
    gpars = gmod.make_params(c=0)
    bmod = ConstantModel(prefix='b_', name='cb')
    bpars = bmod.make_params(c=0)

    for i in np.arange(1, n+1):
        # gmod and bmod sharing the same varible so use the same prefix
        gmod_i = Model(fun_G, prefix='p'+str(i)+'_', name='g'+str(i))
        gpars.update(gmod_i.make_params())
        gpars['p'+str(i)+'_amp'].set(0, min=0)
        gpars['p'+str(i)+'_cen'].set()
        gpars['p'+str(i)+'_wid'].set(1, min=1)
        gpars['p'+str(i)+'_phi'].set(0, min=-np.pi/2, max=np.pi/2)
        bmod_i = Model(fun_B, prefix='p'+str(i)+'_', name='b'+str(i))
        bpars.update(bmod_i.make_params())
        bpars['p'+str(i)+'_amp'].set(0, min=0)
        bpars['p'+str(i)+'_cen'].set()
        bpars['p'+str(i)+'_wid'].set(1, min=1)
        bpars['p'+str(i)+'_phi'].set(0, min=-np.pi/2, max=np.pi/2)
        gmod += gmod_i
        bmod += bmod_i
    
    return gmod, bmod, gpars, bpars


def res_GB(params, f, G, B, **kwargs):
    '''
    residual of both G and B
    '''
    # gmod and bmod have to be assigned to real models
    gmod = kwargs.get('gmod')
    bmod = kwargs.get('bmod')
    eps = kwargs.get('eps', None)
    # eps = 100
    # eps = (G - np.amin(G))
    # eps = pow((G - np.amin(G)*1.001), 1/2)
    
    residual_G = G - gmod.eval(params, x=f)
    residual_B = B - bmod.eval(params, x=f)

    if eps is None:
        return np.concatenate((residual_G, residual_B))
    else:
        return np.concatenate((residual_G * eps, residual_B * eps))


def findpeaks(array, output, sortstr=None, npeaks=np.inf, minpeakheight=-np.inf, 
            threshold=0, minpeakdistance=0, widthreference=None, minpeakwidth=0, maxpeakwidth=np.inf):
    '''
    output: 'indices' or 'values'
    sortstr: 'ascend' or 'descend'
    '''
    # NOTUSING
    indices = np.array([]).astype('int64')
    values = np.array([]).astype('float64')
    data = np.atleast_1d(array).astype('float64')
    if data.size < 3:
        return np.array([])

    hnpeaks = 0
    diffs = data[1:]-data[:-1]
    for i in range(diffs.size-1):
        if hnpeaks >= npeaks:
            break
        if diffs[i] > 0 and diffs[i+1] < 0:
            lthreshold = np.absolute(diffs[i])
            rthreshold = np.absolute(diffs[i+1])
            if data[i+1] >= minpeakheight and lthreshold >= threshold and rthreshold >= threshold:
                indices = np.append(indices, i+1)
                values = np.append(values, data[i+1])
                hnpeaks = hnpeaks + 1

    indices_copy = np.copy(indices)
    if sortstr:
        if sortstr.lower() == 'ascend':
            order = np.argsort(values)
            values = np.sort(values)
            for i in range(order.size):
                indices[i] = indices_copy[order[i]]
        elif sortstr.lower() == 'descend':
            order = np.argsort(-values)
            values = -np.sort(-values)
            for i in range(order.size):
                indices[i] = indices_copy[order[i]]

    if output.lower() == 'indices':
        return indices
    elif output.lower() == 'values':
        return values


def findpeaks_py(x, resonance, output=None, sortstr=None, threshold=None, prominence=None, distance=None, width=None):
    '''
    A wrap up of scipy.signal.find_peaks.
    advantage of find_peaks function of scipy is
    the peaks can be constrained by more properties 
    such as: width, distance etc..
    output: 'indices' or 'values'. if None, return all (indices, heights, prominences, widths)
    sortstr: 'ascend' or 'descend' ordering data by peak height
    '''
    # print(resonance) #testprint
    if x is None or len(x) == 1: # for debuging
        print('findpeaks_py input x is not well assigned!\nx = {}'.format(x))
        exit(0)

    print(threshold) #testprint
    print('f distance', distance / (x[1] - x[0])) #testprint
    print(prominence) #testprint
    print('f width', width / (x[1] - x[0])) #testprint
    peaks, props = find_peaks(
        resonance, 
        threshold=threshold, 
        distance=max(1, distance / (x[1] - x[0])), # make it >= 1
        prominence=prominence,
        width=max(1, width / (x[1] - x[0])), # make it >= 1
    )

    print(peaks) #testprint
    print(props) #testprint
    
    indices = np.copy(peaks)
    values = resonance[indices]
    heights = np.array([])
    prominences = np.array([])
    widths = np.array([])
    if sortstr:
        if sortstr.lower() == 'ascend':
            order = np.argsort(values)
            # values = np.sort(values)
        elif sortstr.lower() == 'descend':
            order = np.argsort(-values)
            values = -np.sort(-values)
        else:
            order = np.argsort(values)
        print(values) #testprint
        print(peaks) #testprint
        print(order) #testprint
        print(props) #testprint

        for i in range(order.size):
            indices[i] = indices[order[i]]
            heights = np.append(heights, props['width_heights'][order[i]])
            prominences = np.append(prominences, props['prominences'][order[i]])
            widths = np.append(widths, props['widths'][order[i]] * (x[1] - x[0])) # in Hz
    
    if output:
        if output.lower() == 'indices':
            return indices
        elif output.lower() == 'values':
            return values
    return indices, heights, prominences, widths


def guess_peak_factors(freq, resonance):
    ''' 
    guess the factors of a peak.
    input:
        freq: frequency
        cen_index: index of center of the peak
        resonance: G or B or modulus
    output:
        amp: amplitude
        cen: peak center
        half_wid: half-maxium hal-width (HMHW)
    '''

    if peak_finder_method == 'simple_func':
        cen_index = np.argmax(resonance) # use max value as peak

        cen = freq[cen_index] # peak center
        # determine the estimated associated conductance (or susceptance) value at the resonance peak
        Rmax = resonance[cen_index] 
        amp = Rmax-np.amin(resonance)
        # determine the estimated half-max conductance (or susceptance) of the resonance peak
        half_max = amp / 2 + np.amin(resonance)
        print('Rmax', Rmax) #testprint
        print('amp', amp) #testprint

        # print('where', np.where(np.abs(half_max-resonance)==np.min(np.abs(half_max-resonance)))) #testprint
        half_wid = np.absolute(freq[np.argmin(np.abs(half_max-resonance))] -  cen)
        print(half_wid) #testprint
        return amp, cen, half_wid, half_max
    elif peak_finder_method == 'py_func': 
        #TODO if find_peaks(x) is necessary?
        cen_index = np.argmax(resonance) # use max value as peak
        prominences = peak_prominences(resonance, np.array([cen_index])) # tuple of 3 arrays
        widths = peak_widths(resonance, np.array([cen_index]), prominence_data=prominences, rel_height=0.5)
        
        cen = freq[cen_index] # peak center
        # use prominence as amp since the peak we are looking for is th tallest one
        amp = prominences[0][0]
        half_wid = min(cen_index-widths[2][0], widths[3][0]-cen_index) * (freq[1] - freq[0]) # min of left and right side
        half_max = widths[1][0]

        return amp, cen, half_wid, half_max


class PeakTracker:

    def __init__(self, max_harm):
        self.max_harm = max_harm
        self.harminput = self.init_harmdict()
        self.harmoutput = self.init_harmdict()
        for harm in range(1, self.max_harm+2, 2):
            harm = str(harm)
            self.update_input('samp', harm , [], [], [], {}, {})
            self.update_input('ref', harm , [], [], [], {}, {})

            self.update_output('samp', harm )
            self.update_output('ref', harm )


        self.active_harm = None
        self.active_chn = None
        self.x = None # temp value (freq) for fitting and tracking
        self.resonance = None # temp value for fitting and tracking
        self.peak_guess = {}
        self.found_n = None

        # ?
        # self.refit_flag = 0
        # self.refit_counter = 1


    def init_harmdict(self):
        '''
        create a dict with for saving input or output data
        '''
        harm_dict = {}
        for i in range(1, self.max_harm+2, 2):
            harm_dict[str(i)] = {}
        chn_dict = {
            'samp': harm_dict,
            'ref' : harm_dict,
            'refit' : harm_dict,
        }
        return chn_dict


    def update_input(self, chn_name, harm, f, G, B, harmdata, freq_span):
        '''
        harmdata: it should be from the main ui self.settings['harmdata']
        if empty harmdata, initialize the key to None
        chn_name: 'samp' or 'ref'
        harm: int
        '''
        if not harmdata: # harmdata is empty (for initialize)
            harm_dict = {}
        else:
            harm_dict = harmdata[chn_name][harm]
        
            print('#### update_input ####') #testprint
            print('chn_name', chn_name, 'harm', harm) #testprint
            print('f[chn][harm]', len(f)) #testprint
            print('harmdata[chn][harm]', harm_dict) #testprint
            print(' #####################') #testprint

        # setattr(self.harminput, chn_name, setattr())
        self.harminput[chn_name][harm]['isfitted'] = False # if the data has been fitted
        self.harminput[chn_name][harm]['f'] = f
        self.harminput[chn_name][harm]['G'] = G
        self.harminput[chn_name][harm]['B'] = B
        if not freq_span:
            self.harminput[chn_name][harm]['current_span'] = [None, None]
        else:
            self.harminput[chn_name][harm]['current_span'] = freq_span[chn_name][harm]
        self.harminput[chn_name][harm]['steps'] = harm_dict.get('lineEdit_scan_harmsteps', None)
        self.harminput[chn_name][harm]['method'] = harm_dict.get('comboBox_tracking_method', None)
        self.harminput[chn_name][harm]['condition'] = harm_dict.get('comboBox_tracking_condition', None)
        self.harminput[chn_name][harm]['fit'] = harm_dict.get('checkBox_harmfit', True)
        self.harminput[chn_name][harm]['factor'] = harm_dict.get('spinBox_harmfitfactor', None)
        self.harminput[chn_name][harm]['n'] = harm_dict.get('spinBox_peaks_num', None)
        
        if harm_dict.get('radioButton_peaks_num_max', None) == True:
            self.harminput[chn_name][harm]['n_policy'] = 'max'
        elif harm_dict.get('radioButton_peaks_num_fixed', None) == True:
            self.harminput[chn_name][harm]['n_policy'] = 'fixed'
        else: # initialize data
            self.harminput[chn_name][harm]['n_policy'] = None
        
        if harm_dict.get('radioButton_peaks_policy_minf', None) == True:
            self.harminput[chn_name][harm]['p_policy'] = 'minf'
        elif harm_dict.get('radioButton_peaks_policy_maxamp', None) == True:
            self.harminput[chn_name][harm]['p_policy'] = 'maxamp'
        else: # initialize data
            self.harminput[chn_name][harm]['p_policy'] = None

        self.harminput[chn_name][harm]['zerophase'] = harm_dict.get('checkBox_settings_settings_harmzerophase', False)
        self.harminput[chn_name][harm]['threshold'] = harm_dict.get('lineEdit_peaks_threshold', None)
        self.harminput[chn_name][harm]['prominence'] = harm_dict.get('lineEdit_peaks_prominence', None)


    def update_output(self, chn_name=None, harm=None, **kwargs):
        '''
        kwargs: keys to update
        chn_name: 'samp' or 'ref'
        harm: int
        '''
        if (chn_name is None) & (harm is None):
            chn_name = self.active_chn
            harm = self.active_harm

        if kwargs:
            for key, val in kwargs.items():
                self.harmoutput[chn_name][harm][key] = val
        else: # initialize
            self.harmoutput[chn_name][harm]['span'] = kwargs.get('span', [np.nan, np.nan])       # span for next scan
            self.harmoutput[chn_name][harm]['cen_trk'] = kwargs.get('cen_trk', np.nan)       # tracking peak center 
            self.harmoutput[chn_name][harm]['factor_span'] = kwargs.get('span', [np.nan, np.nan])       # span of freq used for fitting
            self.harmoutput[chn_name][harm]['method'] = kwargs.get('method', '')       # method for next scan
            self.harmoutput[chn_name][harm]['found_n'] = kwargs.get('found_n', np.nan)       # condition for next scan
            # self.harmoutput[chn_name][harm]['wid'] = kwargs.get('wid', np.nan)       # peak width
            # self.harmoutput[chn_name][harm]['amp'] = kwargs.get('amp', np.nan)       # peak amp
            # self.harmoutput[chn_name][harm]['phi'] = kwargs.get('phi', np.nan)       # phase angle
            self.harmoutput[chn_name][harm]['gmod'] = kwargs.get('gmod', np.nan) # parameters input for clculation
            self.harmoutput[chn_name][harm]['bmod'] = kwargs.get('bmod', np.nan) # parameters input for clculation
            self.harmoutput[chn_name][harm]['params'] = kwargs.get('params', np.nan) # parameters input for clculation
            self.harmoutput[chn_name][harm]['result'] = kwargs.get('result', {}) # clculation result
        
        # print('update params', kwargs.get('params')) #testprint


    def get_input(self, key=None, chn_name=None, harm=None):
        '''
        get val of key from self.harmoutput by chn_name and harm
        if key == None:
            return all of the corresponding chn_name and harm
        '''
        if (chn_name is None) & (harm is None):
            chn_name = self.active_chn
            harm = self.active_harm

        if key is not None:
            return self.harminput[chn_name][harm].get(key, None)
        else: 
            return self.harminput[chn_name][harm] # return all of the corresponding chn_name and harm


    def get_output(self, key=None, chn_name=None, harm=None):
        '''
        get val of key from self.harmoutput by chn_name and harm
        if key == None:
            return all of the corresponding chn_name and harm
        '''
        if (chn_name is None) & (harm is None):
            chn_name = self.active_chn
            harm = self.active_harm

        if key is not None:
            return self.harmoutput[chn_name][harm].get(key, None)
        else: 
            return self.harmoutput[chn_name][harm] # return all of the corresponding chn_name and harm


    def init_active_val(self, chn_name=None, harm=None, method=None):
        '''
        update active values by harm, chn_name
        '''
        if harm is None:
            harm = self.active_harm
        if chn_name is None:
            chn_name = self.active_chn
        if method is None:
            method = self.harminput[chn_name][harm]['method']

        # x and resonance
        if method == 'bmax': # use max susceptance
            self.x = self.harminput[chn_name][harm]['f']
            self.resonance = self.harminput[chn_name][harm]['B']
        elif method == 'derv': # use derivative
            self.resonance = np.sqrt(
                np.diff(self.harminput[chn_name][harm]['G'])**2 + 
                np.diff(self.harminput[chn_name][harm]['B'])**2
            ) # use modulus
            self.x = self.harminput[chn_name][harm]['f'][:-1] + np.diff(self.harminput[chn_name][harm]['f']) # change f size and shift
        elif method == 'prev': # use previous value
            try:
                pre_method = self.harmoutput[chn_name][harm]['method']
                if pre_method == 'prev':
                    pre_method = 'gmax'
            except:
                pre_method = 'gmax'
            
            self.init_active_val(harm=harm, chn_name=chn_name, method=pre_method)
        else:
            self.resonance = self.harminput[chn_name][harm]['G']
            self.x = self.harminput[chn_name][harm]['f']

        self.found_n = 0 # number of found peaks
        self.peak_guess = {} # guess values of found peaks


    ########### peak tracking function ###########
    def peak_tracker(self):
        '''
        track the peak and give the span for next scan
        NOTE: the returned span may out of span_range defined the the main UI!
        '''
        def set_new_cen(freq, cen, current_span, current_xlim):
            ''' set new center '''
            cen_range = settings_init['cen_range'] # cen of span +/- cen_range*span as the accessible range
            cen_diff = cen - np.mean(np.array([freq[0],freq[-1]]))
            print('cen_diff', cen_diff) #testprint
            half_cen_span = cen_range * current_span
            print('half_cen_span', half_cen_span) #testprint
            if np.absolute(cen_diff) > half_cen_span: # out of range
                # new start and end frequencies in Hz
                # return cen # return current peak center as new center
                # OR move the center to the oppsite direction a little incase of a big move of the peak center
                if cen_diff / half_cen_span < -settings_init['big_move_thresh']: # peak on the left side of center range
                    return cen - half_cen_span
                elif cen_diff / half_cen_span > settings_init['big_move_thresh']: # peak on the right side of center range
                    return cen + half_cen_span
                else: # small move use center
                    return cen

            else: 
                # use span center
                # return np.mean(np.array([freq[0],freq[-1]]))
                return np.mean(np.array(current_xlim))

        def set_new_span(current_span, half_wid):
            wid_ratio_range = settings_init['wid_ratio_range'] # width_ratio[0] <= span <= width_ratio[1]
            change_thresh = settings_init['change_thresh'] # span change threshold current_span * change_thresh[0/1]
            ''' set new span '''
            wid_ratio = 0.5 * current_span / half_wid
            print('wid_ratio', wid_ratio) #testprint
            if wid_ratio < wid_ratio_range[0]: # too fat
                return max(
                    min(
                        wid_ratio_range[0] * half_wid * 2, 
                        current_span * (1 + change_thresh[1]),
                    ),
                    current_span * (1 + change_thresh[0])
                )
            elif wid_ratio > wid_ratio_range[1]: # too thin
                print('peak too thin\n',
                    half_wid,
                    wid_ratio_range[1] * half_wid * 2,
                    current_span * (1 - change_thresh[1]),
                    current_span * (1 - change_thresh[0]) # 
                )
                return min(
                    max(
                        wid_ratio_range[1] * half_wid * 2,
                        current_span * (1 - change_thresh[1]),
                        ), # lower bound of wid_ratio_range
                    current_span * (1 - change_thresh[0]) # 
                )
            else:
                return current_span

        def set_new_xlim(new_cen, new_span):
            return [new_cen - 0.5 * new_span, new_cen + 0.5 * new_span]

                
        chn_name = self.active_chn
        harm = self.active_harm
        track_condition = self.harminput[chn_name][harm]['condition']
        track_method = self.harminput[chn_name][harm]['method']
        # determine the structure field that should be used to extract out the initial-guessing method
        freq = self.harminput[chn_name][harm]['f']
        if track_method == 'bmax':
            resonance = self.harminput[chn_name][harm]['B']
        else:
            resonance = self.harminput[chn_name][harm]['G']

        if self.get_output('isfitted', chn_name=chn_name, harm=harm): # data has been fitted
            cen = self.get_fit_values(chn_name=chn_name, harm=harm)['cen_trk']['value']
            half_wid = self.get_fit_values(chn_name=chn_name, harm=harm)['wid_trk']['value']
        else:
            _, cen, half_wid, _ = guess_peak_factors(freq, resonance)
    
        current_xlim = np.array(self.harminput[chn_name][harm]['current_span'])
        # get the current center and current span of the data in Hz
        current_center, current_span = UIModules.converter_startstop_to_centerspan(*self.harminput[chn_name][harm]['current_span'])
        
        # initiate new_xlim == previous span
        new_xlim = self.harminput[chn_name][harm]['current_span']

        # find the starting and ending frequency of only the peak in Hz
        if track_condition == 'fixspan':
            new_cen = set_new_cen(freq, cen, current_span, current_xlim)
            new_xlim = set_new_xlim(new_cen, current_span)
            ''' if np.absolute(np.mean(np.array([freq[0],freq[-1]]))-cen) > 0.1 * current_span:
                # new start and end frequencies in Hz
                new_xlim=np.array([cen-0.5*current_span,cen+0.5*current_span]) '''
        elif track_condition == 'fixcenter':
            new_span = set_new_span(current_span, half_wid)
            new_xlim = set_new_xlim(current_center, new_span)

            ''' # peak_xlim = np.array([cen-half_wid*3, cen+half_wid*3])
            if np.sum(np.absolute(np.subtract(current_xlim, np.array([current_center-3*half_wid, current_center + 3*half_wid])))) > 3e3:
                #TODO above should equal to abs(sp - 6 * half_wid) > 3e3
                # set new start and end freq based on the location of the peak in Hz
                new_xlim = np.array(current_center-3*half_wid, current_center+3*half_wid) '''

        elif track_condition == 'auto':
            new_cen = set_new_cen(freq, cen, current_span, current_xlim)
            new_span = set_new_span(current_span, half_wid)
            new_xlim = set_new_xlim(new_cen, new_span)


            print('current_center', current_center) #testprint
            print('current_span', current_span) #testprint
            print('current_xlim', current_xlim) #testprint
            print('new_cen', new_cen) #testprint
            print('new_span', new_span) #testprint
            print('new_xlim', new_xlim) #testprint

            ''' # adjust window if neither span or center is fixed (default)
            if(np.mean(current_xlim)-cen) > 1*current_span/12: # peak center freq too low
                new_xlim = current_xlim - current_span / 15  # new start and end frequencies in Hz
            elif (np.mean(current_xlim)-cen) < -1*current_span/12: # peak center freq too high
                new_xlim = current_xlim + current_span / 15  # new start and end frequencies in Hz
            else: # peak center in the accessible range
                pass

            thresh1 = .05 * current_span + current_xlim[0] # Threshold frequency in Hz
            thresh2 = .03 * current_span # Threshold frequency span in Hz
            LB_peak = cen - half_wid * 3 # lower bound of the resonance peak
            if LB_peak - thresh1 > half_wid * 8: # if peak is too thin, zoom into the peak
                new_xlim = [(current_xlim[0] + thresh2), (current_xlim[1] - thresh2)] # Hz
            elif thresh1 - LB_peak > -half_wid*5: # if the peak is too fat, zoom out of the peak
                new_xlim = [(current_xlim[0] - thresh2), (current_xlim[1] + thresh2)] # Hz '''
        elif track_condition == 'fixcntspn':
            print('fixcntspn') #testprint
            # bothe span and cent are fixed
            # no changes
            return
        elif track_condition == 'usrdef': #run custom tracking algorithm
            ### CUSTOM, USER-DEFINED
            ### CUSTOM, USER-DEFINED
            ### CUSTOM, USER-DEFINED
            return

        # set new start/end freq in Hz
        self.update_output(chn_name, harm, span=new_xlim)
        self.update_output(chn_name, harm, cen_trk=cen)


    ########### peak finding functions ###########

    ########### initial values guess functions ###
    def params_guess(self, method='gmax'):
        '''
        guess initial values based on given method
        if method == 'bmax': use max susceptance
        'gmax': use max conductance
        'derivative': use modulus
        '''
        # # determine the structure field that should be used to extract out the initial-guessing method
        # if method == 'bmax': # use max susceptance
        #     resonance = B
        #     x = f
        # elif method == 'derv': # use derivative
        #     resonance = np.sqrt(np.diff(G)**2 + np.diff(B)**2) # use modulus
        #     x = f[:-1] + np.diff(f) # change f size and shift
        # elif method == 'prev': # use previous value
        #     # this conditin should not go to this function
        #     return
        # else:
        #     resonance = G
        #     x = f

        phi = 0
        # peak_guess = {}

        chn_name = self.active_chn
        harm = self.active_harm
        n_policy = self.harminput[chn_name][harm]['n_policy']
        p_policy = self.harminput[chn_name][harm]['p_policy']
        print('chn_name', chn_name) #testprint
        print('harm', harm) #testprint
        print('p_policy', p_policy) #testprint
        
        # ordering by peak height decreasing
        if p_policy == 'maxamp':
            sortstr = 'descend' # ordering by peak height decreasing
        elif p_policy == 'minf':
            sortstr = 'descend' # ordering by peak height decreasing

        indices, heights, prominences, widths = findpeaks_py(
            self.x,
            self.resonance, 
            sortstr=sortstr, 
            threshold=self.harminput[chn_name][harm]['threshold'], 
            prominence=self.harminput[chn_name][harm]['prominence'],
            distance=settings_init['peak_min_distance_Hz'], 
            width=settings_init['peak_min_width_Hz']
        )
        
        print('indices', indices) #testprint
        if indices.size == 0:
            self.found_n = 0
            self.update_output(found_n=0)
            return
        
        if method == 'derv':
            # guess phase angle if derivatave method used
            phi = np.arcsin(self.harminput[chn_name][harm]['G'][0] / np.sqrt(self.harminput[chn_name][harm]['G'][0]**2 + self.harminput[chn_name][harm]['B'][0]**2))

        # # for fixed number of peaks (might be added in future) 
        # if n > len(indices):
        #     if n_policy.lower() == 'max':
        #         n = len(indices) # change n to detected number of peaks
        #     elif n_policy.lower() == 'fixed':
        #         # n doesn't need to be changed
        #         pass
        # elif n < len(indices):
        #     # since 'max' and 'fixed' both limited the number not exceeding n, n doesn't need to be changed
        #     pass

        if n_policy == 'max':
            self.found_n = min(len(indices), self.harminput[chn_name][harm]['n'])
        elif n_policy == 'fixed':
            self.found_n = self.harminput[chn_name][harm]['n']

        print(type(self.harminput[chn_name][harm]['n'])) #testprint
        print(indices) #testprint
        print(heights) #testprint
        print(prominences) #testprint
        print(widths) #testprint

        for i in range(self.found_n):
            if i+1 <= len(indices):
                print(i) #testprint
                self.peak_guess[i] = {
                    'amp': prominences[i],  # or use heights
                    'cen': self.x[indices[i]], 
                    'wid': widths[i] / 2, # use half width 
                    'phi': phi
                }
            else: # for fixed number (n > len(indices))
                # add some rough guess values
                # use the min values of each variables
                self.peak_guess[i] = {
                    'amp': np.amin(prominences),  # or use heights. 
                    'cen': self.x[randrange(int(len(self.x) * 0.3), int(len(self.x) * 0.6), self.found_n)], 
                    # devide x range to n parts and randomly choose one. Try to keep the peaks not too close
                    'wid': np.amin(widths) / 2, 
                    'phi': phi
                }
        self.update_output(found_n=self.found_n)
        print('out found', self.harmoutput[chn_name][harm]['found_n']) #testprint


    def prev_guess(self, chn_name=None, harm=None):
        '''
        get previous calculated values and put them into peak_guess
        '''
        if (chn_name is None) & (harm is None):
            chn_name = self.active_chn
            harm = self.active_harm
        
        result = self.harmoutput[chn_name][harm].get('result', None)
        print(result) #testprint
        if not result: # None or empty
            self.peak_guess = {}
            self.found_n = 0
            self.update_output(found_n=0)
            return

        val = result.params.valuesdict()

        print(self.harmoutput[chn_name][harm]['found_n']) #testprint
        print(self.harminput[chn_name][harm]['n']) #testprint
        n_policy = self.harminput[chn_name][harm]['n_policy']

        # set self.found_n and leave self.harmoutput[chn_name][harm]['found_n'] as the peaks found
        if n_policy == 'max':
            self.found_n = min(self.harmoutput[chn_name][harm]['found_n'], self.harminput[chn_name][harm]['n'])
        elif n_policy == 'fixed':
            self.found_n = self.harminput[chn_name][harm]['n']

        for i in np.arange(self.found_n):
            if i+1 <= self.harmoutput[chn_name][harm]['found_n']:
                pre_str = 'p' + str(i) + '_'
                self.peak_guess[i] = {
                    'amp': val[pre_str + 'amp'], 
                    'cen': val[pre_str + 'cen'], 
                    'wid': val[pre_str + 'wid'], 
                    'phi': val[pre_str + 'phi'], 
                }
            else: # for fixed number (n > len(indices))
                # add some rough guess values
                # use the last values of each variables
                self.peak_guess[i] = {
                    'amp': self.peak_guess[self.harmoutput[chn_name][harm]['found_n']-1]['amp'],  
                    'cen': self.x[randrange(int(len(self.x) * 0.3), int(len(self.x) * 0.6), self.found_n)], 
                    # devide x range to n parts and randomly choose one. Try to keep the peaks not too close
                    'wid': self.peak_guess[self.harmoutput[chn_name][harm]['found_n']-1]['wid'], 
                    'phi': self.peak_guess[self.harmoutput[chn_name][harm]['found_n']-1]['phi'],
                }
        # now update 'found_n in harmoutput
        self.update_output(chn_name, harm, found_n=self.found_n)


    def auto_guess(self):
        '''
        auto guess the peak parameters by using the given 
        method. If method is not give, choose the method 
        in a loop in case failed.
        return guessing method used and peak_guess
        The loop is defined as 
        method_list = ['gmax', 'bmax', 'derv', 'prev']
        '''
        if self.harminput[self.active_chn][self.active_harm]['method'] == 'auto':
            method_list = ['gmax', 'bmax', 'derv', 'prev']
        else:
            method_list = [self.harminput[self.active_chn][self.active_harm]['method']]

        for method in method_list:
            print(method) #testprint
            if method == 'prev':
                self.prev_guess()
            else:
                self.params_guess(method=method)

            if self.found_n: # not None and 0
                self.update_output(method=method)
                break 
        

    def set_params(self, chn_name=None, harm=None):
        ''' set the parameters for fitting '''
        if (chn_name is None) & (harm is None):
            chn_name = self.active_chn
            harm = self.active_harm

        params = Parameters()

        # rough guess
        f = self.get_input(key='f', chn_name=chn_name, harm=harm)
        G = self.get_input(key='G', chn_name=chn_name, harm=harm)
        B = self.get_input(key='B', chn_name=chn_name, harm=harm)
        amp_rough = np.amax(self.resonance) - np.amin(self.resonance)
        cen_rough = np.mean(f)
        wid_rough = (np.amax(f) - np.amin(f)) / 6
        phi_rough = 0

        print('prek_guess', self.peak_guess) #testprint

        if self.found_n == 0: # no peak found by find_peak_py
            self.found_n = 1 # force it to at least 1 for fitting
            self.update_output(found_n=1) # force it to at least 1 for fitting

        for i in np.arange(self.found_n):
            if not self.peak_guess: 
                amp = amp_rough
                cen = cen_rough
                wid = wid_rough
                phi = phi_rough
            else:
                amp = self.peak_guess[i].get('amp', amp_rough)
                cen = self.peak_guess[i].get('cen', cen_rough)
                wid = self.peak_guess[i].get('wid', wid_rough)
                phi = self.peak_guess[i].get('phi', phi_rough)

            params.add(
                'p'+str(i)+'_amp',      # amplitude (G)
                value=amp,              # init: peak height
                min=0,                  # lb
                max=np.inf,             # ub
            )
            params.add(
                'p'+str(i)+'_cen',      # center 
                value=cen,              # init: average f
                min=np.amin(f),         # lb: assume peak is in the range of f
                max=np.amax(f),         # ub: assume peak is in the range of f
            )
            params.add(
                'p'+str(i)+'_wid',                 # width (hwhm)
                value=wid,                         # init: half range
                # min= settings_init['peak_min_width_Hz'] / 2,         # lb in Hz (this limit sometime makes the peaks to thin)
                min= wid / 10,         # lb in Hz (limit the width >= 1/10 of the guess value!!)
                max=(np.amax(f) - np.amin(f)) * 2, # ub in Hz: assume peak is in the range of f
            )
            if self.harminput[chn_name][harm]['zerophase']: # fix phase to 0
                params.add(
                    'p'+str(i)+'_phi',       # phase shift
                    value=0,                 # init value: peak height
                    vary=False,              # fix phi=0
                    min=-np.pi / 2,          # lb in rad
                    max=np.pi / 2,           # ub in rad
                )
            else: # leave phase vary
                params.add(
                    'p'+str(i)+'_phi',       # phase shift
                    value=phi,               # init value: peak height
                    min=-np.pi / 2,          # lb in rad
                    max=np.pi / 2,           # ub in rad
                )
        
        params.add(
            'g_c',              # initialize G_offset
            value=np.amin(G),    # init G_offset = mean(G)
        )        
        params.add(
            'b_c',              # initialize B_offset
            value=np.mean(B),   # init B_offset = mean(B)
        )
        self.update_output(params=params)


    ########### fitting ##########################
    def minimize_GB(self):
        '''
        use leasesq to fit
        '''
        chn_name = self.active_chn
        harm = self.active_harm
        factor =self.get_input(key='factor')

        print('chn', chn_name, 'harm', harm) #testprint
        print(self.get_output()) #testprint
        print('mm factor', factor) #testprint
        print('self n', self.found_n) #testprint
        # set params with data
        self.auto_guess()
        self.set_params()

        print('self n', self.found_n) #testprint

        # set the models
        gmod, bmod = make_gbmodel(self.found_n)
        self.update_output(gmod=gmod)
        self.update_output(bmod=bmod)
        

        f = self.harminput[chn_name][harm]['f']
        G = self.harminput[chn_name][harm]['G']
        B = self.harminput[chn_name][harm]['B']

        val = self.get_output(key='params').valuesdict() # get guessed values

        # set data for fitting by factor
        # min_idx = min(min indices)
        # max_idx = max(max indices)
        # all the points between will be used for fitting
        
        factor_idx_list = [] # for factor_span
        factor_set_list = [] # for indexing the points for fitting
        if factor is not None:
            for i in range(self.found_n): # for loop for each single peak from guessed val
                # get peak cen and wid
                cen_i, wid_i = val['p' + str(i) + '_cen'], val['p' + str(i) + '_wid']
                print('cen_i', cen_i) #testprint
                print('wid_i', wid_i) #testprint
                ind_min = np.abs(self.harminput[chn_name][harm]['f'] - (cen_i - wid_i * factor)).argmin()
                ind_max = np.abs(self.harminput[chn_name][harm]['f'] - (cen_i + wid_i * factor)).argmin()
                # factor_idx_list.append(ind_min) # add min index 
                # factor_idx_list.append(ind_max) # add max index 
                # or use one line
                factor_idx_list.extend([ind_min, ind_max])
                # get indices for this peak in form of set
                factor_set_list.append(set(np.arange(ind_min, ind_max)))
                
            # find the union of sets
            idx_list = list(set().union(*factor_set_list))
            # mask of if points used for fitting
            factor_mask = [True if i in idx_list else False for i in np.arange(len(f))]

            # save min_idx and max_idx to 'factor_span'
            self.update_output(chn_name=chn_name, harm=harm, factor_span=[min(f[factor_idx_list]), max(f[factor_idx_list])]) # span of f used for fitting

            f = f[idx_list]
            G = G[idx_list]
            B = B[idx_list]

            print('data len after factor', len(f)) #testprint

        print('factor\n', factor) #testprint
        # print('cen_guess\n', cen_guess) #testprint
        # print('half_wid_guess\n', half_wid_guess) #testprint
        # print('factor_span\n', factor_span) #testprint
        # minimize with leastsq
        # mini = Minimizer(residual, params, fcn_args=(f, G, B))
        # result = mini.leastsq(xtol=1.e-10, ftol=1.e-10)
        eps = None
        # eps = pow((G - np.amin(G)*1.001), 1/2) # residual weight
        # print(f) #testprint
        # print(G) #testprint
        # print(B) #testprint
        print('mm params', self.harmoutput[chn_name][harm]['params']) #testprint
        try:
            result = minimize(
                res_GB, 
                self.get_output(key='params'), 
                method='leastsq', 
                args=(f, G, B), 
                kws={'gmod': gmod, 'bmod': bmod, 'eps': eps}, 
                xtol=settings_init['xtol'], ftol=settings_init['ftol'],
                nan_policy='omit', # ('raise' default, 'propagate', 'omit')
                )
            print(fit_report(result)) 
            print('success', result.success)
            print('message', result.message)
            print('lmdif_message', result.lmdif_message)
        except Exception as err:
            result = {}
            traceback.print_tb(err.__traceback__)
            print(err)

        self.update_output(chn_name, harm, result=result)


    def get_fit_values(self, chn_name=None, harm=None):
        '''
        get values from calculated result
        '''

        if (chn_name is None) & (harm is None):
            chn_name = self.active_chn
            harm = self.active_harm
            
        p_policy = self.harminput[chn_name][harm]['p_policy']
        result = self.harmoutput[chn_name][harm]['result'] 
        found_n = self.harmoutput[chn_name][harm]['found_n']
    
        # get values of the first peak (index = 0, peaks are ordered by p_policy)
        val = {}
        if result:
            # check peak order by amp and cen
            amp_array = np.array([result.params.get('p' + str(i) + '_amp').value for i in range(found_n)])
            cen_array = np.array([result.params.get('p' + str(i) + '_cen').value for i in range(found_n)])

            print('found_n', found_n) #testprint
            print(result.params) #testprint
            print('params', result.params.valuesdict()) #testprint
            print(amp_array) #testprint
            print(cen_array) #testprint
            # get max amp index
            maxamp_idx = np.argmax(amp_array)
            # get min cen index
            mincen_idx = np.argmin(cen_array)

            # since we are always tracking the peak with maxamp
            p_trk = maxamp_idx
            # get recording peak key by p_policy
            if p_policy == 'maxamp':
                p_rec = maxamp_idx
            elif p_policy == 'minf':
                p_rec = mincen_idx

            # values for tracking peak
            val['amp_trk'] = {
                'value' : result.params.get('p' + str(p_trk) + '_amp').value,
                'stderr': result.params.get('p' + str(p_trk) + '_amp').stderr,
            }
            val['cen_trk'] = {
                'value' : result.params.get('p' + str(p_trk) + '_cen').value,
                'stderr': result.params.get('p' + str(p_trk) + '_cen').stderr,
            }
            val['wid_trk'] = {
                'value' : result.params.get('p' + str(p_trk) + '_wid').value,
                'stderr': result.params.get('p' + str(p_trk) + '_wid').stderr,
            }
            val['phi_trk'] = {
                'value' : result.params.get('p' + str(p_trk) + '_phi').value,
                'stderr': result.params.get('p' + str(p_trk) + '_phi').stderr,
            }

            # values for recording peak
            val['amp_rec'] = {
                'value' : result.params.get('p' + str(p_rec) + '_amp').value,
                'stderr': result.params.get('p' + str(p_rec) + '_amp').stderr,
            }
            val['cen_rec'] = {
                'value' : result.params.get('p' + str(p_rec) + '_cen').value,
                'stderr': result.params.get('p' + str(p_rec) + '_cen').stderr,
            }
            val['wid_rec'] = {
                'value' : result.params.get('p' + str(p_rec) + '_wid').value,
                'stderr': result.params.get('p' + str(p_rec) + '_wid').stderr,
            }
            val['phi_rec'] = {
                'value' : result.params.get('p' + str(p_rec) + '_phi').value,
                'stderr': result.params.get('p' + str(p_rec) + '_phi').stderr,
            }

            val['g_c'] = {
                'value' : result.params.get('g_c').value,
                'stderr': result.params.get('g_c').stderr,
            }
            val['b_c'] = {
                'value' : result.params.get('b_c').value,
                'stderr': result.params.get('b_c').stderr,
            }

            val['sucess'] = result.success # bool
            val['chisqr'] = result.chisqr # float

            print('params', result.params.valuesdict()) #testprint
        else:
            # values for tracking peak
            val['amp_trk'] = {
                'value' : np.nan,
                'stderr': np.nan,
            }
            val['cen_trk'] = {
                'value' : np.nan,
                'stderr': np.nan,
            }
            val['wid_trk'] = {
                'value' : np.nan,
                'stderr': np.nan,
            }
            val['phi_trk'] = {
                'value' : np.nan,
                'stderr': np.nan,
            }

            # values for recording peak
            val['amp_rec'] = {
                'value' : np.nan,
                'stderr': np.nan,
            }
            val['cen_rec'] = {
                'value' : np.nan,
                'stderr': np.nan,
            }
            val['wid_rec'] = {
                'value' : np.nan,
                'stderr': np.nan,
            }
            val['phi_rec'] = {
                'value' : np.nan,
                'stderr': np.nan,
            }

            val['g_c'] = {
                'value' : np.nan,
                'stderr': np.nan,
            }
            val['b_c'] = {
                'value' : np.nan,
                'stderr': np.nan,
            }

            val['sucess'] = False # bool
            val['chisqr'] = np.nan # float

        return val


    def eval_mod(self, mod_name, chn_name=None, harm=None, components=False):
        '''
        evaluate gmod or bmod by f
        return ndarray
        '''
        if (chn_name is None) & (harm is None):
            chn_name = self.active_chn
            harm = self.active_harm

        if self.harmoutput[chn_name][harm]['result']:
            if components is False: # total fitting
                return self.get_output(key=mod_name, chn_name=chn_name, harm=harm).eval(
                    self.harmoutput[chn_name][harm]['result'].params, 
                    x=self.harminput[chn_name][harm]['f']
                    )
            else: # return divided peaks
                # make gmod and bmod for all components
                gmods, bmods = make_models(n=self.harmoutput[chn_name][harm]['found_n'])
                if mod_name == 'gmod':
                    g_fit = [] # list of G fit values by peaks
                    for gmod in gmods:
                        g_fit.append(
                            gmod.eval(
                                self.harmoutput[chn_name][harm]['result'].params, 
                                x=self.harminput[chn_name][harm]['f'],
                            )
                        )
                    return g_fit
                elif mod_name == 'bmod':
                    b_fit = [] # list of B fit values by peaks
                    for bmod in bmods:
                        b_fit.append(
                            bmod.eval(
                                self.get_output(key='result', chn_name=chn_name, harm=harm).params, 
                                x=self.get_input(key='f', chn_name=chn_name, harm=harm)
                            )
                        )
                    return b_fit
                else: # no mod_name matched
                    dummy = []
                    for _ in range(self.get_output(key='found_n', chn_name=chn_name, harm=harm)):
                        dummy.append(np.empty(self.harminput[chn_name][harm]['f'].shape) * np.nan)
                    return dummy
        else: # no result found
            if components is False: # total fitting
                return np.empty(self.harminput[chn_name][harm]['f'].shape) * np.nan # array
            else: # return divided peaks
                return [np.empty(self.harminput[chn_name][harm]['f'].shape) * np.nan] # array of array


    ########### warp up functions ################
    # MAKE SURE: run self.update_input(chn_name, harm, f, G, B, harmdata) first to import scan data
    def peak_track(self, chn_name=None, harm=None):
        '''
        The whole process of peak tracking
        return the predicted span
        '''
        # change the active chn_name and harm
        if (chn_name is not None) & (harm is not None):
            self.active_chn = chn_name
            self.active_harm = harm

        self.peak_tracker()

        return self.harmoutput[chn_name][harm]['span'], self.harmoutput[chn_name][harm]['cen_trk']


    def peak_fit(self, chn_name=None, harm=None, components=False):
        '''
        The whole process of peak fitting
        return: 
            the dict of values with std errors
            fitted G value
            fitted B value
            if components == True:
                list fitted G values by peaks
                list fitted B values by peaks
        '''
        # change the active chn_name and harm
        if (chn_name is not None) & (harm is not None):
            self.active_chn = chn_name
            self.active_harm = harm
        
        self.init_active_val(chn_name=chn_name, harm=harm)
        print('chn:', chn_name, 'harm:', harm) #testprint
        print('self.chn:', self.active_chn, 'self.harm:', self.active_harm) #testprint

        self.minimize_GB()
        
        if components is False:
            return {
                'v_fit': self.get_fit_values(chn_name=chn_name, harm=harm), # fitting factors
                'fit_g': self.eval_mod('gmod', chn_name=chn_name, harm=harm), # fitted value of G
                'fit_b': self.eval_mod('bmod', chn_name=chn_name, harm=harm), # fitted value of B
                'factor_span': self.get_output(key='factor_span', chn_name=chn_name, harm=harm)
            } 
        elif components is True:
            return {
                'v_fit': self.get_fit_values(chn_name=chn_name, harm=harm),
                'fit_g': self.eval_mod('gmod', chn_name=chn_name, harm=harm),
                'fit_b': self.eval_mod('bmod', chn_name=chn_name, harm=harm),
                'comp_g': self.eval_mod('gmod', chn_name=chn_name, harm=harm, components=True), # list of fitted G value of each peak
                'comp_b': self.eval_mod('bmod', chn_name=chn_name, harm=harm, components=True), # list of fitted B value of each peak
            }


    def fit_result_report(self, fit_result=None):
        # if not fit_result:
        #     # chn_name = self.active_chn
        #     # harm = self.active_harm
        #     fit_result = self.get_output(key='result')
        # return fit_report(fit_result, show_correl=False, )

        v_fit = self.get_fit_values()
        print(v_fit) #testprint
        keys = {
            # 'Sucess': 'sucess',
            # u'\u03A7' + 'sq': 'chisqr',
            'f (Hz)': 'cen_rec',
            u'\u0393' + ' (Hz)': 'wid_rec',
            u'\u03A6' + ' (deg.)': 'phi_rec',
            'G_amp (mS)': 'amp_rec',
            'G_shift (mS)': 'g_c',
            'B_shift (mS)': 'b_c',
        }

        buff = []

        buff.append('Sucess:\t{}'.format(v_fit['sucess']))
        buff.append(u'\u03A7' + 'sq:\t{:.7g}'.format(v_fit['chisqr']))
        
        for txt, key in keys.items():
            txt = '{}:\t'.format(txt)
            if v_fit[key].get('value') is not None:
                txt = '{}{:.7g}'.format(txt, v_fit[key].get('value')*180/np.pi if key == 'phi_rec' else v_fit[key].get('value'))
            if v_fit[key].get('stderr') is not None:
                txt = '{} +/- {:.7g}'.format(txt, v_fit[key].get('stderr')*180/np.pi if key == 'phi_rec' else v_fit[key].get('stderr'))
            buff.append(txt)
        return '\n'.join(buff)


if __name__ == '__main__':
    import matplotlib.pyplot as plt
    try:
        from AccessMyVNA_dummy import AccessMyVNA
    except:
        from Modules.AccessMyVNA_dummy import AccessMyVNA 

    # gbfitting = GBFitting()
    # # print(gbfitting.gmodel.param_names)
    # # print(gbfitting.bmodel.param_names)
    # # print(gbfitting.gpars)
    # # print(gbfitting.bpars)

    # gmod = gbfitting.gmodel
    # bmod = gbfitting.bmodel
    accvna = AccessMyVNA()
    _, f, G = accvna.GetScanData(nWhata=-1, nWhatb=15)
    _, _, B = accvna.GetScanData(nWhata=-1, nWhatb=16)


    n = 2

    # result = minimize_GB(f, G, B, n, )
    # params = set_params(f, G, B, n)
    # result = minimize(res_GB, params, method='leastsq', args=(f, G, B), kws={'eps': pow((G - np.amin(G)*1.001), 1/2), 'n': n}, xtol=1.e-10, ftol=1.e-10)
    # eixt(0)
    # print(fit_report(result)) 
    # print('success', result.success)
    # print('message', result.message)
    # print('lmdif_message', result.lmdif_message)
    print('params', result.params.get('p0_cen').value)
    print('params', result.params.get('p0_cen').stderr)
    print('params', result.params.valuesdict())
    # print(result.params)
    # print(params['p1_amp'].vary)

    # exit(0)
    gmod, bmod = make_gbmodel(n)
    gmods, bmods = make_models(n)
    # gpars = gmod.guess(G, x=f) #guess() not implemented for CompositeModel
    plt.figure()
    plt.plot(f, G, 'bo')
    plt.plot(f, gmod.eval(result.params, x=f), 'k--')
    if n > 1:
        for i in range(n):
            plt.plot(f, gmods[i].eval(result.params, x=f))
    plt.twinx()
    plt.plot(f, B, 'go')
    plt.plot(f, bmod.eval(result.params, x=f), 'k--')
    if n > 1:
        for i in range(n):
            plt.plot(f, bmods[i].eval(result.params, x=f))

    plt.figure()
    plt.plot(G, B, 'bo')
    plt.plot(gmod.eval(result.params, x=f), bmod.eval(result.params, x=f), 'k--')
    if n > 1:
        for i in range(n):
            plt.plot(gmods[i].eval(result.params, x=f), bmods[i].eval(result.params, x=f))

    plt.figure()
    Y = np.sqrt(np.diff(G)**2 + np.diff(B)**2)
    Y_fit = np.sqrt(np.diff(gmod.eval(result.params, x=f))**2 + np.diff(bmod.eval(result.params, x=f))**2)
    print(len(f[0:-1]), len(np.diff(f)))
    df = f[0:-1] + np.diff(f)
    plt.plot(df, Y, 'bo')
    plt.plot(df, Y_fit, 'k--')
    if n > 1:
        for i in range(n):
            Y_fit = np.sqrt(np.diff(gmods[i].eval(result.params, x=f))**2 + np.diff(bmods[i].eval(params, x=f))**2)
            plt.plot(df, Y)

    plt.show()
    exit(0)

    plot_components = True
    # plot results
    fig = plt.figure()
    plt.plot(f, G, 'bo')
    if plot_components:
        # generate components
        comps = result.eval_components(x=f)
        plt.plot(f, 10*comps['cg'], 'k--')
        plt.plot(f, 10*comps['cb'], 'r-')
    else:
        plt.plot(f, result.init_fit, 'k--')
        plt.plot(f, result.best_fit, 'r-')

    result = bmod.fit(B, params=params, x=f)
    print(result.fit_report())
    plt.show()
    exit(1)
    plot_components = False
    # plot results
    fig = plt.figure()
    plt.plot(f, B, 'bo')
    if plot_components:
        # generate components
        comps = result.eval_components(x=f)
        plt.plot(f, 10*comps['jump'], 'k--')
        plt.plot(f, 10*comps['gaussian'], 'r-')
    else:
        plt.plot(f, result.init_fit, 'k--')
        plt.plot(f, result.best_fit, 'r-')
    plt.show()