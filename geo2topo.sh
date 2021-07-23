#!/bin/bash -ex
GEOJSON=$1
TOPOJSON=$2
sudo npm install -g topojson
geo2topo -q 1000 "$GEOJSON" > "$TOPOJSON"
