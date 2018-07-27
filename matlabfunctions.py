import math
import numpy as np

def num2str(A,precision=None, formatSpec=None):
    if isinstance(A, np.ndarray):
        if A.any() and not precision and not formatSpec:
            for i in range(len(A)):
                A[i] = str(float(A[i]))
            return A
        elif A.any() and precision and not formatSpec:
            for i in range(len(A)):
                A[i] = format(float(A[i]), '.'+str(precision)+'g')
            return A
        elif A.any() and formatSpec:
            print('not implemented')
        else:
            print('not available')
    elif isinstance(A, float) or isinstance(A, int):
        if A and not precision and not formatSpec:
            A = str(float(A))
            return A
        elif A and precision and not formatSpec:
            A = format(float(A), '.'+str(precision)+'g')
            return A
        elif A and formatSpec:
            print('not implemented')
        else:
            print('not available')

def findpeaks(array, output, sortstr=None, npeaks=np.inf, minpeakheight=-np.inf, 
            threshold=0, minpeakdistance=0, widthreference=None, minpeakwidth=0, maxpeakwidth=np.inf):
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