preview-live:
	docker run --rm -it -v `pwd`:/vol -w /vol -p 8000:8000 circleci/node:8.2 npm run build
	aws s3 sync --delete --acl public-read --cache-control 'public, max-age=30' WEBSITE_OUTPUT/ s3://planscore-2020-site-update/
