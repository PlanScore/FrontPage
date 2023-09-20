#!/usr/bin/env python3
import collections
import csv
import math
import os
import sys

Bucket = collections.namedtuple('Bucket', ('left', 'count'))

pixelwidth, pixelheight = 536, 237

eg_xmin, eg_xmax = -.25, .25
eg_breaks = [i/100 for i in range(-25, 26, 2)]
eg_ranges = [[mn, round(mn/2 + mx/2, 6), mx] for (mn, mx) in zip(eg_breaks, eg_breaks[1:])]
eg_ranges[0][0], eg_ranges[-1][-1] = -math.inf, math.inf

pb_xmin, pb_xmax = -.25, .25
pb_breaks = [i/100 for i in range(-25, 26, 2)]
pb_ranges = [[mn, round(mn/2 + mx/2, 6), mx] for (mn, mx) in zip(pb_breaks, pb_breaks[1:])]
pb_ranges[0][0], pb_ranges[-1][-1] = -math.inf, math.inf

dec_xmin, dec_xmax = -.81, .81
dec_breaks = [i/100 for i in range(-84, 85, 7)]
dec_ranges = [[mn, round(mn/2 + mx/2, 6), mx] for (mn, mx) in zip(dec_breaks, dec_breaks[1:])]
dec_ranges[0][0], dec_ranges[-1][-1] = -math.inf, math.inf

mmd_xmin, mmd_xmax = -.12, .12
mmd_breaks = [i/100 for i in range(-12, 13, 1)]
mmd_ranges = [[mn, round(mn/2 + mx/2, 6), mx] for (mn, mx) in zip(mmd_breaks, mmd_breaks[1:])]
mmd_ranges[0][0], mmd_ranges[-1][-1] = -math.inf, math.inf

if __name__ == '__main__':
    destination = sys.argv[1]
    
    if destination.endswith('_eg_plan_curve.svg'):
        xmin, xmax, ranges, = eg_xmin, eg_xmax, eg_ranges
    elif destination.endswith('_bias_plan_curve.svg'):
        xmin, xmax, ranges, = pb_xmin, pb_xmax, pb_ranges
    elif destination.endswith('_dec2_plan_curve.svg'):
        xmin, xmax, ranges, = dec_xmin, dec_xmax, dec_ranges
    elif destination.endswith('_mmd_plan_curve.svg'):
        xmin, xmax, ranges, = mmd_xmin, mmd_xmax, mmd_ranges
    else:
        raise ValueError(destination)
    
    buckets = [
        Bucket(float(row[-2]), int(row[-1] or '0'))
        for row in csv.reader(sys.stdin, dialect='excel-tab')
    ]
    
    stride = (buckets[-1].left - buckets[0].left) / (len(buckets) - 1)
    buckets.insert(0, Bucket(buckets[0].left - stride, 0))
    buckets.insert(0, Bucket(buckets[0].left - stride, 0))
    buckets.append(Bucket(buckets[-1].left + stride, 0))
    buckets.append(Bucket(buckets[-1].left + stride, 0))
    
    ceil = max(bucket.count for bucket in buckets)
    histogram = {(None, bucket.left, None): bucket.count for bucket in buckets}
    
    tx = lambda x: round(pixelwidth * ((x - xmin) / (xmax - xmin)), 1)
    ty = lambda y: round(pixelheight - y * .9 * pixelheight / ceil, 1)
    path = [f'M {tx(xmin)} {ty(0)}']
    hlist = list(histogram.items())
    hlists = zip(hlist, hlist[1:], hlist[2:], hlist[3:])
    for (((_, x1, _), y1), ((_, x2, _), y2), ((_, x3, _), y3), ((_, x4, _), y4)) in hlists:
        slope1 = (y3 - y1) / (x3 - x1)
        slope2 = (y4 - y2) / (x4 - x2)
        c0 = x2 * 2/3 + x3 * 1/3
        c1 = y2 + slope1 * (x3 - x2) / 3
        c2 = x2 * 1/3 + x3 * 2/3
        c3 = y3 - slope2 * (x3 - x2) / 3
        path.append(f'C {tx(c0)} {ty(c1)} {tx(c2)} {ty(c3)} {tx(x3)} {ty(y3)}')
    path.extend([f'L {tx(xmax)} {ty(0)}', f'L {tx(xmin)} {ty(0)}', 'Z'])
    d = ' '.join(path)
    print(d)

    # Find the balance point for the gradient as a percentage
    left = min(xmin, min(n for ((_, n, _), _) in hlist[2:]))
    right = max(xmax, max(n for ((_, n, _), _) in hlist[:-1]))
    middle = 100 * abs(left) / (abs(left) + right)
    
    with open(destination, 'w') as file:
        print(f'''<?xml version="1.0" encoding="UTF-8"?>
<svg width="{pixelwidth}px" height="{pixelheight}px" viewBox="0 0 {pixelwidth} {pixelheight}" version="1.1" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
    <!-- Generator: Sketch 51.3 (57544) - http://www.bohemiancoding.com/sketch -->
    <title>{os.path.splitext(os.path.basename(destination))[0]}</title>
    <desc>Created with Sketch.</desc>
    <defs>
        <linearGradient x1="{middle - 40}%" y1="0%" x2="{middle + 40}%" y2="0%" id="linearGradient-1">
            <stop stop-color="#CD3952" offset="0%"></stop>
            <stop stop-color="#DFDFDF" offset="50%"></stop>
            <stop stop-color="#0A4FAB" offset="100%"></stop>
        </linearGradient>
    </defs>
    <g id="ushouse_eg_plan_curve" stroke="none" stroke-width="1" fill="none" fill-rule="evenodd">
        <path d="{d}" id="Shape" fill="url(#linearGradient-1)" transform="translate({pixelwidth} 0) scale(-1, 1)"></path>
        <polygon id="Shape" fill="#C6C6C6" points="0 0 0 235 0 237 2 237 268 237 270 237 534 237 536 237 536 235 536 0 534 0 534 235 270 235 270 0 268 0 268 235 2 235 2 0"></polygon>
    </g>
</svg>''', file=file)
