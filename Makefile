preview-live:
	docker run --rm -it -v `pwd`:/vol -w /vol circleci/node:lts npm run build
	aws s3 sync --delete --acl public-read --cache-control 'public, max-age=30' WEBSITE_OUTPUT/ s3://planscore-2020-site-update/

WEBSITE_OUTPUT/data/electionoutcomes_statehouse-raw.csv: WEBSITE_OUTPUT/data/107slers20210522.dta.csv.gz
	csvgrep -c outcome -m w $^ \
		| csvgrep -c sen -m 0 \
		| csvgrep -c etype -r '[gs]+$$' \
		| csvcut -c outcome,sen,etype,dno,sab,year,partyt \
		| pv -l > $@

WEBSITE_OUTPUT/data/electionoutcomes_statesenate-raw.csv: WEBSITE_OUTPUT/data/107slers20210522.dta.csv.gz
	csvgrep -c outcome -m w $^ \
		| csvgrep -c sen -m 1 \
		| csvgrep -c etype -r '[gs]+$$' \
		| csvcut -c outcome,sen,etype,dno,sab,year,partyt \
		| pv -l > $@

WEBSITE_OUTPUT/data/districtpolygons/%.json: WEBSITE_OUTPUT/data/districtpolygons/%.geojson
	docker run --rm -it -v `pwd`:/vol -w /vol circleci/node:lts \
		./geo2topo.sh $^ $@
