# Testing Session Start/Stop Tests

## Issue

We have run into issues where when we start a session, then the AMS reads the PLC tag to stop the session, if we start a new session right after, we somttimes get lag and freeze. 

## What I think is the problem

I beleive that the time it takes the edge containers to deploy and remove is a certain amount of time. And when we start a session directly after ending one, the containers may not be ready to redeploy.

## Proposed Solution

Have a edge device ready flag that shows the status of our edge containers. We need to know if the edge containers are ready to deploy. Also we need to know exactly when the edge containers are deployed and ready on the edge hosts device. This way we know exactly when we can push start on the robot controller.

## Tasks

determine if my ideation of the problem is correct, then analyze my solution and determine what scafolding we already have to determine container readiness.

Plan out a fix.
