We need to move the pgadmin away from the NAS. Currently we have the scafolding to move the pgadmin into this AMS using a docker container. This is the approach we need to use.

When we setup the pgadmin into a container here, we need to insure we use a server instance. I want there to be accounts on this instance for me and other students. This way we can isolate querys and make sure we dont run into imporopper management of querying. We want this pgadmin container to be fast, and not throttle.
