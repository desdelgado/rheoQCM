#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Jan  4 09:19:59 2018

@author: ken
"""
import numpy as np
from scipy.optimize import least_squares
import matplotlib.pyplot as plt
import os
import hdf5storage
from pathlib import Path
from functools import reduce

zq = 8.84e6  # shear acoustic impedance of quartz
f1 = 5e6  # fundamental resonant frequency


def fstar_err_calc(fstar):
    # calculate the error in delfstar
    g_err_min = 10 # error floor for gamma
    f_err_min = 50 # error floor for f
    err_frac = 3e-2 # error in f or gamma as a fraction of gamma
    # start by specifying the error input parameters
    fstar_err = np. zeros(1, dtype=np.complex128)
    fstar_err = (max(f_err_min, err_frac*real(fstar)) + 1j*
                 max(g_err_min, err_frac*imag(fstar)))
    return fstar_err


def cosd(phi):  # need to define matlab-like functions that accept degrees
    return np.cos(np.deg2rad(phi))


def sind(phi):  # need to define matlab-like functions that accept degrees
    return np.sin(np.deg2rad(phi))


def tand(phi):  # need to define matlab-like functions that accept degrees
    return np.tan(np.deg2rad(phi))


def real(x):  # define real part of a number so we don't alays have to add np.
    return np.real(x)


def imag(x):  # as above, for imaginary part
    return np.imag(x)


def sauerbreyf(n, drho):
    return 2*n*f1 ** 2*drho/zq


def sauerbreym(n, delf):
    return delf*zq/(2*n*f1 ** 2)


def grho(n, grho3, phi):
    return grho3*(n/3) ** (phi/90)


def grho_from_dlam(n, drho, dlam, phi):
    return (drho*n*f1*cosd(phi/2)/dlam) ** 2


def grho3_bulk(delfstar):
    return (np.pi*zq*abs(delfstar[3])/f1) ** 2


def phi_bulk(n, delfstar):
    return -np.degrees(2*np.arctan(real(delfstar[n]) /
                       imag(delfstar[n])))


def lamrho3_calc(grho3, phi):
    return np.sqrt(grho3)/(3*f1*cosd(phi/2))


def D(n, drho, grho3, phi):
    return 2*np.pi*drho*n*f1*(cosd(phi/2) - 1j*sind(phi/2)) / \
        (grho(n, grho3, phi)) ** 0.5


# calcuated complex frequency shift for single layer
def delfstarcalc_onelayer(n, drho, grho3, phi):
    return -sauerbreyf(n, drho)*np.tan(D(n, drho, grho3, phi)) / \
        D(n, drho, grho3, phi)


# calculated complex frequency shift for bulk layer
def delfstarcalc_bulk(n, grho3, phi):
    return ((f1*np.sqrt(grho(n, grho3, phi)) / (np.pi*zq)) *
            (-sind(phi/2)+ 1j * cosd(phi/2)))


def d_lamcalc(n, drho, grho3, phi):
    return drho*n*f1*cosd(phi/2)/np.sqrt(grho(n, grho3, phi))


def thin_film_gamma(n, drho, jdprime_rho):
    return 8*np.pi ** 2*n ** 3*f1 ** 4*drho ** 3*jdprime_rho / (3*zq)
    # same master expression, replacing grho3 with jdprime_rho3


def grho3(jdprime_rho3, phi):
    return sind(phi)/jdprime_rho3


def dlam(n, dlam3, phi):
    return dlam3*(int(n)/3) ** (1-phi/180)


def normdelfstar(n, dlam3, phi):
    return -np.tan(2*np.pi*dlam(n, dlam3, phi)*(1-1j*tand(phi/2))) / \
        (2*np.pi*dlam(n, dlam3, phi)*(1-1j*tand(phi/2)))


def rhcalc(nh, dlam3, phi):
    return real(normdelfstar(nh[0], dlam3, phi)) / \
        real(normdelfstar(nh[1], dlam3, phi))


def rh_from_delfstar(nh, delfstar):
    # nh here is the calc string (i.e., '353')
    n1 = int(nh[0])
    n2 = int(nh[1])
    return (n2/n1)*real(delfstar[n1])/real(delfstar[n2])


def rdcalc(nh, dlam3, phi):
    return -imag(normdelfstar(nh[2], dlam3, phi)) / \
        real(normdelfstar(nh[2], dlam3, phi))


def rd_from_delfstar(n, delfstar):
    # dissipation ratio calculated for the relevant harmonic
    return -imag(delfstar[n])/real(delfstar[n])


def solve_onelayer(soln_input):
    # bulk solution to the QCM master equation.
    nhplot = soln_input['nhplot']
    nh = soln_input['nh']
    n1 = int(nh[0])
    n2 = int(nh[1])
    n3 = int(nh[2])
    delfstar = soln_input['delfstar']

    # first pass at solution comes from rh and rd
    rd_exp = -imag(delfstar[n3])/real(delfstar[n3])
    rh_exp = (n2/n1)*real(delfstar[n1])/real(delfstar[n2])

    if 'prop_guess' in soln_input:
        drho = soln_input['propguess']['drho']
        grho3 = soln_input['propguess']['grho3']
        phi = soln_input['propguess']['phi']
        soln1_guess = guess_from_props(drho, grho3, phi)
    elif rd_exp > 0.5:
        soln1_guess = bulk_guess(delfstar)
    else:
        soln1_guess = thinfilm_guess(delfstar)

    lb = [0, 0]  # lower bounds on dlam3 and phi
    ub = [5, 90]  # upper bonds on dlam3 and phi

    def ftosolve(x):
        return [rhcalc(nh, x[0], x[1])-rh_exp, rdcalc(nh, x[0], x[1])-rd_exp]

    soln1 = least_squares(ftosolve, soln1_guess, bounds=(lb, ub))

    dlam3 = soln1['x'][0]
    phi = soln1['x'][1]
    drho = (sauerbreym(n1, real(delfstar[n1])) /
            real(normdelfstar(n1, dlam3, phi)))
    grho3 = grho_from_dlam(3, drho, dlam3, phi)

    # we solve it again to get the Jacobian with respect to our actual
    # input variables - this is helpfulf for the error analysis
    x0 = np.array([drho, grho3, phi])

    def ftosolve2(x):
        return ([real(delfstar[n1]) -
                real(delfstarcalc_onelayer(n1, x[0], x[1], x[2])),
                real(delfstar[n2]) -
                real(delfstarcalc_onelayer(n2, x[0], x[1], x[2])),
                imag(delfstar[n3]) -
                imag(delfstarcalc_onelayer(n3, x[0], x[1], x[2]))])

    soln2 = least_squares(ftosolve2, x0)
    drho = soln2['x'][0]
    grho3 = soln2['x'][1]
    phi = soln2['x'][2]
    dlam3 = d_lamcalc(3, drho, grho3, phi)

    # now back calculate delfstar, rh and rdfrom the solution
    delfstar_calc = {}
    rh = {}
    rd = {}
    for n in nhplot:
        delfstar_calc[n] = delfstarcalc_onelayer(n, drho, grho3, phi)
        rd[n] = rd_from_delfstar(n, delfstar_calc)
    rh = rh_from_delfstar(nh, delfstar_calc)

    soln_output = {'drho': drho, 'grho3': grho3, 'phi': phi, 'dlam3': dlam3,
                   'delfstar_calc': delfstar_calc, 'rh': rh, 'rd': rd}
    
    # now calculate the error in the solution
    # start by putting the input uncertainties into a 3 element vector
    delfstar_err = np.zeros(3)
    delfstar_err[0] = real(soln_input['delfstar_err'][n1])
    delfstar_err[1] = real(soln_input['delfstar_err'][n2])
    delfstar_err[2] = imag(soln_input['delfstar_err'][n3])
    
    # use these uncertainties along with the Jacobian from the solution
    # to determine the uncertainties in the measured parameters
    jac = soln2['jac']
    jac_inv = np.linalg.inv(jac)
    err = {}
    err_names=['drho', 'grho3', 'phi']
    for k in [0, 1, 2]:
        err[err_names[k]] = ((jac_inv[k, 0]*delfstar_err[0])**2 + 
                            (jac_inv[k, 1]*delfstar_err[1])**2 +
                            (jac_inv[k, 2]*delfstar_err[2])**2)**0.5

    soln_output['err'] = err
    return soln_output


def QCManalyze(sample, parms):
    # read in the optional inputs, assigning default values if not assigned
    nhplot = sample.get('nhplot', [1, 3, 5])
    # firstline = sample.get('firstline', 0)
    sample['xlabel'] = sample.get('xlabel',  't (min.)')
    Temp = np.array(sample.get('Temp', [22]))

    # set the appropriate value for xdata
    if Temp.shape[0] != 1:
        sample['xlabel'] = r'$T \: (^\circ$C)'

    sample['nhcalc'] = sample.get('nhcalc', ['355'])
    imagetype = parms.get('imagetype', 'svg')
    figlocation = parms.get('figlocation', 'figures')

    # specify the location for the output figure files
    if figlocation == 'datadir':
        base_fig_name = sample['datadir']+sample['filmfile']
    else:
        base_fig_name = 'figures/'+sample['samplename']
        if not os.path.exists('figures'):
            os.mkdir('figures')

    imagetype = parms.get('imagetype', 'svg')

    # set the color dictionary for the different harmonics
    colors = {1: [1, 0, 0], 3: [0, 0.5, 0], 5: [0, 0, 1]}

    # now set the markers used for the different calculation types
    markers = {'131': '>', '133': '^', '353': '+', '355': 'x', '3': 'x'}

    # initialize the dictionary we'll use to keep track of the points to plot
    idx = {}

    # plot and process bare crystal data
    bare = process_raw(sample, 'bare')
    
    # plot and process the film data
    film = process_raw(sample, 'film')
    
    # if there is only one temperature, than we use time as the x axis, using
    # up to ten user-selected points
    if Temp.shape[0] == 1:
        nx = min(10, film['n_all'], bare['n_all'])
    else:
        nx = Temp.shape[0]
    
    # pick the points that we want to analyze and add them to the plots
    for dict in [bare, film]:
        dict['idx'] = pickpoints(Temp, nx, dict)
        dict['fstar_err'] = {}
        idx = dict['idx']
        for n in nhplot:
            dict['fstar_err'][n] = np.zeros(dict['n_all'], dtype=np.complex128)
            for i in idx:
                dict['fstar_err'][n][i] = fstar_err_calc(dict['fstar'][n][i])
                t = dict['t'][i]
                f = real(dict['fstar'][n][i])/n
                g = imag(dict['fstar'][n][i])
                f_err = real(dict['fstar_err'][n][i])/n
                g_err = imag(dict['fstar_err'][n][i])
                dict['f_ax'].errorbar(t, f, yerr=f_err, color=colors[n],
                                      label='n='+str(n), marker='x')
                dict['g_ax'].errorbar(t, g, yerr=g_err, color=colors[n],
                                       label='n='+str(n), marker='x')

    # adjust nhcalc to account to only include calculations for for which
    # the data exist
    sample['nhcalc'] = nhcalc_in_nhplot(sample['nhcalc'], nhplot)

    # there is nothing left to do if nhcalc has no values
    if not(sample['nhcalc']):
        return

    # now calculate the frequency and dissipation shifts
    delfstar = {}
    delfstar_err = {}
    for i in np.arange(nx):
        idxb = bare['idx'][i]
        idxf = film['idx'][i]
        delfstar[i] = {}
        delfstar_err[i] ={}
        for n in nhplot:
            delfstar[i][n] = (film['fstar'][n][idxf] - 
                              bare['fstar'][n][idxb])
            delfstar_err[i][n] = fstar_err_calc(film['fstar'][n][idxf])

    # set up the property axes
    propfig = make_prop_axes(sample)
    checkfig = {}
    for nh in sample['nhcalc']:
        checkfig[nh] = make_check_axes(sample, nh)

    # set the appropriate value for xdata
    if Temp.shape[0] == 1:
        xdata = film['t'][film['idx']]
    else:
        xdata = Temp

    # now do all of the calculations and plot the data
    soln_input = {'nhplot': nhplot}
    results = {}

    # now we set calculation and plot all of the desired solutions
    for nh in sample['nhcalc']:
        results[nh] = {'drho': np.zeros(nx), 'grho3': np.zeros(nx),
                       'phi': np.zeros(nx), 'dlam3': np.zeros(nx),
                       'lamrho3': np.zeros(nx), 'rd': {}, 'rh': {},
                       'delfstar_calc': {}, 'drho_err': np.zeros(nx),
                       'grho3_err': np.zeros(nx), 'phi_err': np.zeros(nx)}
        for n in nhplot:
            results[nh]['delfstar_calc'][n] = (np.zeros(nx,
                                               dtype=np.complex128))
            results[nh]['rd'][n] = np.zeros(nx)

        results[nh]['rh'] = np.zeros(nx)

        for i in np.arange(nx):
            # obtain the solution for the properties
            soln_input['nh'] = nh
            soln_input['delfstar'] = delfstar[i]
            soln_input['delfstar_err'] = delfstar_err[i]
            soln = solve_onelayer(soln_input)

            results[nh]['drho'][i] = soln['drho']
            results[nh]['grho3'][i] = soln['grho3']
            results[nh]['phi'][i] = soln['phi']
            results[nh]['dlam3'][i] = soln['dlam3']
            results[nh]['drho_err'][i] = soln['err']['drho']
            results[nh]['grho3_err'][i] = soln['err']['grho3']
            results[nh]['phi_err'][i] = soln['err']['phi']

            for n in nhplot:
                results[nh]['delfstar_calc'][n][i] = (
                 soln['delfstar_calc'][n])
                results[nh]['rd'][n][i] = soln['rd'][n]
            results[nh]['rh'][i] = soln['rh']

            # add actual values of delf, delg for each harmonic to the
            # solution check figure
            for n in nhplot:
                checkfig[nh]['delf_ax'].plot(xdata[i], real(delfstar[i][n])
                                             / n, '+', color=colors[n])
                checkfig[nh]['delg_ax'].plot(xdata[i], imag(delfstar[i][n]),
                                             '+', color=colors[n])
            # add experimental rh, rd to solution check figure
            checkfig[nh]['rh_ax'].plot(xdata[i], rh_from_delfstar(nh,
                                       delfstar[i]), '+', color=colors[n])

            for n in nhplot:
                checkfig[nh]['rd_ax'].plot(xdata[i], rd_from_delfstar(n,
                                           delfstar[i]), '+', color=colors[n])

        # add the calculated values of rh, rd to the solution check figures
        checkfig[nh]['rh_ax'].plot(xdata, results[nh]['rh'], '-')
        for n in nhplot:
            checkfig[nh]['rd_ax'].plot(xdata, results[nh]['rd'][n], '-',
                                       color=colors[n])

        # add calculated delf and delg to solution check figures
        for n in nhplot:
            (checkfig[nh]['delf_ax'].plot(xdata,
             real(results[nh]['delfstar_calc'][n]) / n, '-',
             color=colors[n], label='n='+str(n)))
            (checkfig[nh]['delg_ax'].plot(xdata,
             imag(results[nh]['delfstar_calc'][n]), '-', color=colors[n],
             label='n='+str(n)))

        # add legen to the solution check figures
        checkfig[nh]['delf_ax'].legend()
        checkfig[nh]['delg_ax'].legend()

        # tidy up the solution check figure
        checkfig[nh]['figure'].tight_layout()
        checkfig[nh]['figure'].savefig(base_fig_name + '_'+nh +
                                       '.' + imagetype)

        # add property data to the property figure
        drho = 1000*results[nh]['drho']
        grho3 = results[nh]['grho3']/1000
        phi = results[nh]['phi']
        drho_err = 1000*results[nh]['drho_err']
        grho3_err = results[nh]['grho3_err']/1000
        phi_err = results[nh]['phi_err']
        
        propfig['drho_ax'].errorbar(xdata, drho, yerr=drho_err,
                                    marker=markers[nh], label=nh)
        propfig['grho_ax'].errorbar(xdata, grho3, yerr=grho3_err,
                                    marker=markers[nh], label=nh)
        propfig['phi_ax'].errorbar(xdata, phi, yerr=phi_err,
                                    marker=markers[nh], label=nh)
        output_data = np.stack((xdata, drho, grho3, phi), axis=-1)
        np.savetxt(base_fig_name+'_'+nh+'.txt', output_data, 
                   delimiter=',', header='xdata, drho, grho, phi')

    # add legends to the property figure
    propfig['drho_ax'].legend()
    propfig['grho_ax'].legend()
    propfig['phi_ax'].legend()

    # tidy up the raw data and property figures
    propfig['figure'].tight_layout()
    propfig['figure'].savefig(base_fig_name+'_prop.'+imagetype)

    print('done with ', base_fig_name, 'close plots with ctrl+w')

    plt.show()


def idx_in_range(t, t_range):
    if t_range[0] == t_range[1]:
        idx = np.arange(t.shape[0]).astype(int)
    else:
        idx = np.where((t > t_range[0]) &
                       (t < t_range[1]))[0]
    return idx


def nhcalc_in_nhplot(nhcalc_in, nhplot):
    # there is probably a more elegant way to do this
    # only consider harmonics in nhcalc that exist in nhplot
    nhcalc_out = []
    nhplot = list(set(nhplot))
    for nh in nhcalc_in:
        nhlist = list(set(nh))
        nhlist = [int(i) for i in nhlist]
        if all(elem in nhplot for elem in nhlist):
            nhcalc_out.append(nh)
    return nhcalc_out


def pickpoints(Temp, nx, dict):
    t_in = dict['t']
    idx_in = dict['idx_all']
    idx_file = dict['idx_file']
    idx_out = np.array([], dtype=int)
    if Temp.shape[0] == 1:
        t = np.linspace(min(t_in[idx_in]), max(t_in[idx_in]), nx)
        for n in np.arange(nx):
            idx_out = np.append(idx_out, (np.abs(t[n] - t_in)).argmin())
        idx_out = np.asarray(idx_out)

    elif idx_file.is_file():
        idx_out = np.loadtxt(idx_file, dtype=int)
    else:
        # make the correct figure active
        plt.figure(dict['rawfigname'])
        print('click on plot to pick ', str(nx), 'points')
        pts = plt.ginput(nx)
        pts = np.array(pts)[:, 0]
        for n in np.arange(nx):
            idx_out = np.append(idx_out, (np.abs(pts[n] - t_in)).argmin())
        idx_out = np.asarray(idx_out)
        np.savetxt(idx_file, idx_out, fmt='%4i')

    return idx_out


def make_prop_axes(sample):
    # set up the property plot
    if plt.fignum_exists('prop'):
        plt.close('prop')
    fig = plt.figure('prop', figsize=(9, 3))
    drho_ax = fig.add_subplot(131)
    drho_ax.set_xlabel(sample['xlabel'])
    drho_ax.set_ylabel(r'$d\rho\: (g/m^2)$')

    grho_ax = fig.add_subplot(132)
    grho_ax.set_xlabel(sample['xlabel'])
    grho_ax.set_ylabel(r'$|G_3^*|\rho \: (Pa \cdot g/cm^3)$')

    phi_ax = fig.add_subplot(133)
    phi_ax.set_xlabel(sample['xlabel'])
    phi_ax.set_ylabel(r'$\phi$ (deg.)')

    fig.tight_layout()

    return {'figure': fig, 'drho_ax': drho_ax, 'grho_ax': grho_ax,
            'phi_ax': phi_ax}


def process_raw(sample, data_type):
    colors = {1: [1, 0, 0], 3: [0, 0.5, 0], 5: [0, 0, 1]}
    # specify the film filenames
    firstline = sample.get('firstline', 0)
    nhplot = sample.get('nhplot', [1, 3, 5])
    trange = sample.get(data_type+'trange', [0, 0])
    dict = {}
    dict['file'] = sample['datadir'] + sample[data_type+'file'] + '.mat'
    dict['data'] = hdf5storage.loadmat(dict['file'])
    dict['idx_file'] = Path(sample['datadir']+sample[data_type+'file']+
                            '_film_idx.txt')

    # extract the frequency data from the appropriate file
    freq = dict['data']['abs_freq'][firstline:, 0:7]

    # get rid of all the rows that don't have any data
    freq = freq[~np.isnan(freq[:, 1:]).all(axis=1)]

    # reference frequencies are the first data points for the bare crystal data
    sample['freqref'] = sample.get('freqref', freq[0, :])

    # extract frequency information
    dict['t'] = freq[:, 0]
    dict['fstar'] = {}

    for n in nhplot:        
        dict['fstar'][n] = freq[:, n] +1j*freq[:, n+1] - sample['freqref'][n]

    #  find all the time points between specified by timerange
    #  if the min and max values for the time range are equal, we use
    #    all the points
    dict['idx_all'] = idx_in_range(dict['t'], trange)

    # figure out how man total points we have
    dict['n_all'] = dict['idx_all'].shape[0]

    # rewrite nhplot to account for the fact that data may not exist for all
    # of the harmonics
    dict['n_exist'] = np.array([]).astype(int)

    for n in nhplot:
        if not all(np.isnan(dict['fstar'][n])):
            dict['n_exist'] = np.append(dict['n_exist'], n)
            
    # make the figure with its axis
    rawfigname = 'raw_'+data_type
    if plt.fignum_exists(rawfigname):
        plt.close(rawfigname)
    dict['rawfig'] = plt.figure(rawfigname)

    dict['f_ax'] = dict['rawfig'].add_subplot(121)
    dict['f_ax'].set_xlabel('t (min.)')
    dict['f_ax'].set_ylabel(r'$\Delta f_n/n$ (Hz)')
    dict['f_ax'].set_title(data_type)

    dict['g_ax'] = dict['rawfig'].add_subplot(122)
    dict['g_ax'].set_xlabel('t (min.)')
    dict['g_ax'].set_ylabel(r'$\Gamma$ (Hz)')
    dict['g_ax'].set_title(data_type)
    
    # plot the raw data
    for n in nhplot:
        t = dict['t'][dict['idx_all']]
        f = real(dict['fstar'][n][dict['idx_all']])/n
        g = imag(dict['fstar'][n][dict['idx_all']])
        (dict['f_ax'].plot(t, f, color=colors[n], label='n='+str(n)))
        (dict['g_ax'].plot(t, g, color=colors[n], label='n='+str(n)))

    # add the legends
    dict['f_ax'].legend()
    dict['g_ax'].legend()
    
    dict['rawfig'].tight_layout() 
    dict['rawfigname'] = rawfigname
    
    return dict


def make_check_axes(sample, nh):
    if plt.fignum_exists(nh + 'solution check'):
        plt.close(nh + 'solution check')
    #  compare actual annd recaulated frequency and dissipation shifts.
    fig = plt.figure(nh + 'solution check')
    delf_ax = fig.add_subplot(221)
    delf_ax.set_xlabel(sample['xlabel'])
    delf_ax.set_ylabel(r'$\Delta f/n$ (Hz)')

    delg_ax = fig.add_subplot(222)
    delg_ax.set_xlabel(sample['xlabel'])
    delg_ax.set_ylabel(r'$\Delta \Gamma$ (Hz)')

    rh_ax = fig.add_subplot(223)
    rh_ax.set_xlabel(sample['xlabel'])
    rh_ax.set_ylabel(r'$r_h$')

    rd_ax = fig.add_subplot(224)
    rd_ax.set_xlabel(sample['xlabel'])
    rd_ax.set_ylabel(r'$r_d$')

    fig.tight_layout()

    return {'figure': fig, 'delf_ax': delf_ax, 'delg_ax': delg_ax,
            'rh_ax': rh_ax, 'rd_ax': rd_ax}


def bulk_guess(delfstar):
    # get the bulk solution for grho and phi
    grho3 = (np.pi*zq*abs(delfstar[3])/f1) ** 2
    phi = -np.degrees(2*np.arctan(real(delfstar[3]) /
                      imag(delfstar[3])))

    # calculate rho*lambda
    lamrho3 = np.sqrt(grho3)/(3*f1*cosd(phi/2))

    # we need an estimate for drho.  We only use thi approach if it is
    # reasonably large.  We'll put it at the quarter wavelength condition
    # for now

    drho = lamrho3/4
    dlam3 = d_lamcalc(3, drho, grho3, phi)

    return [dlam3, min(phi, 90)]


def guess_from_props(drho, grho3, phi):
    dlam3 = d_lamcalc(3, drho, grho3, phi)
    return [dlam3, phi]


def thinfilm_guess(delfstar):
    # really a placeholder function until we develop a more creative strategy
    # for estimating the starting point
    return [0.05, 5]

