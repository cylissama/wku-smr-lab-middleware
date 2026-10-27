I noticed that the web container currently relies on the connection to the database to properly load. This means that our web and maybe the fastapi containers wont spin up unless we have a connection activley to the database. So if we dont  have a connection, or say its connection gos out before startup then we wont be able to start this.

I would like to decouple the deployment of the web container from the database connection.

That is to say that if we do launch out web container, and the database conneciton either does not work or there are erros, these errors should display on the dashbaord.

Come up with a plan to implement this. Keep in mind that we are building a fault tolerant system here, so the design of each container should alwasy work to redploy itself when possible if it were to fault, and also to verbosly log and disaply why the system is not working.
