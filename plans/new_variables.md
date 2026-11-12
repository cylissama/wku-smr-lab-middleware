# New overrideable variables

On the dashbaord we need to be able to set 2 more variables

Currently the camera nodes take save_frame and save_annotations (or something similar)

These are True by default.

We need to be able to turn these to False


The purpose of this is to not store theses frames and annotaitons on the camera pi itself. We just want to send them straight out to the AMS for processing and storage. As no image processing should be done on the pi.


