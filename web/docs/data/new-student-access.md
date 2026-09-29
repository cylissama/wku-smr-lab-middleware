# Getting database access (new students)

Students can't sign themselves up for pgAdmin. A lab admin creates your account and gives you a password. It takes three steps:

1. **You** ask a lab admin for an account.
2. **The admin** creates your pgAdmin login and your database role.
3. **You** log in, change your pgAdmin password and connect to the database.

For what you can do once you're in, and the query rules, see [Accessing the database](/data/accessing-database.md).

## 1. Request an account (student)

Send a lab admin:

- **Your email address.** This is your pgAdmin username.
- **The database username you want.** Use lowercase letters, digits and underscores only, for example `jsmith` (first initial and last name). Each person gets their own, so don't ask to share one.
- **What you need to do.** Students get **viewer** access (read-only) unless there's a reason for more.

You'll also need to be on the lab network. pgAdmin can't be reached from outside it.

## 2. Create the account (admin)

Run these from the repo root on the Data Broker Mini PC (`192.168.2.100`), with the stack running.

1. Add the student to `pgadmin/users.csv` (gitignored), one line per person:

   ```text
   jsmith@wku.edu,jsmith,viewer
   ```

   The columns are `email,db_role,group`. `group` is `viewer` or `admin`, and blank means viewer. Leave the existing lines in place; people who already have an account are skipped.

2. Run the provisioning script:

   ```bash
   pgadmin/provision-users.sh --apply
   ```

   For each new person it prints `added jsmith@wku.edu (viewer, db role: jsmith)`, then `applied ...`. It creates:
   - the pgAdmin login, using the restricted `Viewer` pgAdmin role
   - the `ManufactoringDB` server in their pgAdmin, under the `smr-db` group, set to log in as their own role
   - their Postgres role in `lab_viewers`, with the viewer limits (read-only, 2 min query timeout, 5 connections)

   If it prints `error: pgAdmin accounts were created but the Postgres roles were not`, fix the error it shows, then run the `pgadmin/generated/lab-roles-*.sql` file it names in the Query Tool as `DB_USER`. Re-running the script won't redo it, because the pgAdmin account already exists.

3. Open the newest `pgadmin/generated/credentials-*.csv` and give the student their line (email, database username, password) in person or by direct message. Don't post it in a group channel.

4. Add the student to the "Lab members" section of `.accounts`, then delete both generated files. They hold the password in plain text:

   ```bash
   rm pgadmin/generated/credentials-*.csv pgadmin/generated/lab-roles-*.sql
   ```

To check it worked, the student should show up in pgAdmin under **User Management** (the user menu at the top right), and this should return their role in `lab_viewers`:

```sql
SELECT r.rolname, g.rolname AS member_of
FROM pg_roles r
JOIN pg_auth_members m ON m.member = r.oid
JOIN pg_roles g ON g.oid = m.roleid
WHERE r.rolname = 'jsmith';
```

## 3. First login (student)

1. On the lab network, go to [http://192.168.2.100:5050](http://192.168.2.100:5050). The Data Dashboard also links to it.
2. Log in with your email and the password the admin gave you.
3. **Change your pgAdmin password:** click your email at the top right, then **Change Password**.

   This only changes your pgAdmin login. **Your database password stays the original one the admin gave you,** so keep it.

4. In the left panel, open **smr-db → ManufactoringDB**. When it asks for a password, enter the **original** password from the admin.

   If you tick **Save Password**, pgAdmin asks you to set a master password. It uses the master password to lock your saved database password, and asks for it each time you log in.

5. Check that it works. Open **Tools → Query Tool** and run:

   ```sql
   SELECT id, label, started_at FROM session ORDER BY id DESC LIMIT 5;
   ```

   You should see the five most recent test sessions.

Then read [Accessing the database](/data/accessing-database.md) before running queries on the big tables. Filter on `session_id`, or your queries will hit the 2 minute limit.

## If something goes wrong

| What you see | What it means |
| --- | --- |
| The page doesn't load | You're not on the lab network. |
| `password authentication failed for user "..."` when opening ManufactoringDB | You entered your new pgAdmin password. Use the original one the admin gave you. |
| `too many connections for role "..."` | You have 5 connections open. Close Query Tool tabs you aren't using. |
| `canceling statement due to statement timeout` | The query ran longer than 2 minutes. Filter on `session_id` and use `LIMIT`. |
| `cannot execute INSERT in a read-only transaction` | Viewer accounts are read-only. That's expected. |
| Forgot your pgAdmin password or database password | Ask a lab admin to reset it. |
