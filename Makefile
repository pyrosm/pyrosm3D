# Clean the build folders, the test cache and the coverage files
.PHONY: clean
clean:
	rm -f .coverage
	rm -f coverage.xml
	rm -rf pyrosm3d.egg-info
	rm -rf build
	rm -rf .pytest_cache
	rm -rf dist
