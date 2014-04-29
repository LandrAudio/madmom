#!/usr/bin/env python
# encoding: utf-8
"""
This file contains tempo related functionality.

@author: Sebastian Böck <sebastian.boeck@jku.at>

"""

import numpy as np
from scipy.signal import argrelmax

from . import Event


# helper functions
def smooth_signal(signal, smooth):
    """
    Smooth the given signal.

    :param signal: signal
    :param smooth: smoothing kernel [array or int]
    :returns:      smoothed signal

    """
    # init smoothing kernel
    kernel = None
    # size for the smoothing kernel is given
    if isinstance(smooth, int):
        if smooth > 1:
            kernel = np.hamming(smooth)
    # otherwise use the given smoothing kernel directly
    elif isinstance(smooth, np.ndarray):
        if len(smooth) > 1:
            kernel = smooth
    # check if a kernel is given
    if kernel is None:
        raise ValueError('can not smooth signal with %s' % smooth)
    # convolve with the kernel and return
    return np.convolve(signal, kernel, 'same')


def smooth_histogram(histogram, smooth):
    """
    Smooth the given histogram.

    :param histogram: histogram
    :param smooth:    smoothing kernel [array or int]
    :returns:         smoothed histogram

    """
    # smooth only the the histogram bins, not the corresponding delays
    return smooth_signal(histogram[0], smooth), histogram[1]


# interval detection
def interval_histogram(activations, smooth=None, min_tau=1, max_tau=None):
    """
    Compute the interval histogram of the given activation function.

    :param activations: the activation function
    :param smooth:      kernel (size) for smoothing the activation function
                        before auto-correlating it. [array or int]
    :param min_tau:     minimal delta for correlation function [frames]
    :param max_tau:     maximal delta for correlation function [frames]
    :returns:           histogram

    """
    # smooth activations
    if smooth:
        activations = smooth_signal(activations, smooth)
    # set the maximum delay
    if max_tau is None:
        max_tau = len(activations) - min_tau
    # test all possible delays
    taus = range(min_tau, max_tau)
    bins = []
    # TODO: make this processing parallel or numpyfy if possible
    for tau in taus:
        bins.append(np.sum(np.abs(activations[tau:] * activations[0:-tau])))
    # return histogram
    return np.array(bins), np.array(taus)


def dominant_interval(histogram, smooth=None):
    """
    Extract the dominant interval of the given histogram.

    :param histogram: histogram with interval distribution
    :param smooth:    smooth the histogram with the given kernel (size)
    :returns:         dominant interval

    """
    # smooth the histogram bins
    if smooth:
        histogram = smooth_histogram(histogram, smooth)
    # return the dominant interval
    return histogram[1][np.argmax(histogram[0])]


def log3(x):
    """
    Takes the logarithm to the basis of 3.

    :param x: array like
    :return:  logarithm to the basis of 3
    """
    return np.log(x) / np.log(3)


# default values for tempo estimation
ACT_SMOOTH = 0.13
MIN_BPM = 40
MAX_BPM = 240
HIST_SMOOTH = 5
NO_TEMPO = np.nan
GROUPING_DEV = 0


class Tempo(Event):
    """
    Tempo Class.

    """
    def __init__(self, activations, fps, sep=''):
        """
        Creates a new Tempo instance with the given beat activations.
        The activations can be read in from file.

        :param activations: array with the beat activations or a file (handle)
        :param fps:         frame rate of the activations
        :param sep:         separator if activations are read from file

        """
        super(Tempo, self).__init__(activations, fps, sep)

    def detect(self, act_smooth=ACT_SMOOTH, hist_smooth=HIST_SMOOTH,
               min_bpm=MIN_BPM, max_bpm=MAX_BPM, grouping_dev=GROUPING_DEV):
        """
        Detect the tempo on basis of the given beat activation function.

        :param act_smooth:   smooth the activation function over N seconds
        :param hist_smooth:  smooth the activation function over N bins
        :param min_bpm:      minimum tempo to detect
        :param max_bpm:      maximum tempo to detect
        :param grouping_dev: allowed tempo deviation for grouping tempi
        :returns:            tuple with the two most dominant tempi and the
                             relative strength of them

        Note: If the 'grouping_dev' is set to 0, the tempi are not grouped.
              The deviation is allowed delta in the log2 / log3 space.

        """
        # convert the arguments to frames
        act_smooth = int(round(self.fps * act_smooth))
        min_tau = int(np.floor(60. * self.fps / max_bpm))
        max_tau = int(np.ceil(60. * self.fps / min_bpm))
        # generate a histogram of beat intervals
        histogram = interval_histogram(self.activations, smooth=act_smooth,
                                       min_tau=min_tau, max_tau=max_tau)
        # smooth the histogram again
        if hist_smooth:
            histogram = smooth_histogram(histogram, smooth=hist_smooth)
        # the histogram bins
        bins = histogram[0]
        # convert the histogram bin delays to tempi in beats per minute
        tempi = 60.0 * self.fps / histogram[1]
        # to get the two dominant tempi, just keep the peaks
        # use 'wrap' mode to also get peaks at the borders
        peaks = argrelmax(bins, mode='wrap')[0]
        # we need more than 1 peak to report multiple tempi
        if len(peaks) == 0:
            # no peaks, no tempo
            return NO_TEMPO, NO_TEMPO, 0.
        elif len(peaks) == 1:
            # report only the strongest tempo
            return tempi[peaks[0]], NO_TEMPO, 1.
        else:
            # sort the peaks in descending order of bin heights
            sorted_peaks = peaks[np.argsort(bins[peaks])[::-1]]
            # group the corresponding tempi if needed
            if grouping_dev:
                # get the peak tempi
                t = tempi[sorted_peaks]
                # get the whole-numbered divisors from all tempo combinations
                c = t / t[:, np.newaxis]
                # group all double tempi
                # transform the fractions to the log2 space
                double_c = np.abs(np.log2(c))
                # and keep only those within a certain deviation
                double_c = np.round(double_c / grouping_dev) * grouping_dev
                double_c = double_c % 1 == 0
                # get the corresponding strengths
                double = bins[sorted_peaks][np.newaxis, :] * double_c
                # select the winning combination
                double_tempi = double[np.argmax(np.sum(double_c, axis=1))]
                # group all triple tempi
                # transform the fractions to the log3 space
                triple_c = np.abs(log3(c))
                # again, keep only those within a certain deviation
                triple_c = np.round(triple_c / grouping_dev) * grouping_dev
                triple_c = triple_c % 1 == 0
                # get the corresponding strengths
                triple = bins[sorted_peaks][np.newaxis, :] * triple_c
                # select the winning combination
                triple_tempi = triple[np.argmax(np.sum(triple_c, axis=1))]
                # combine the double and triple tempo combinations
                strengths = np.max((double_tempi, triple_tempi), axis=0)
                # re-sort the peaks
                sorted_peaks = sorted_peaks[np.argsort(strengths)[::-1]]
            # otherwise just return the 2 strongest tempi
            t1, t2 = tempi[sorted_peaks[:2]]
            # calculate the relative strength
            strength = bins[sorted_peaks[0]]
            strength /= np.sum(bins[sorted_peaks[:2]])
            return t1, t2, strength