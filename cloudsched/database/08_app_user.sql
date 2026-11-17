-- =====================================================================================
-- CloudSched  |  08_app_user.sql  |  OPTIONAL: a least-privilege MySQL account for the API (instead of root)
-- Run once as root AFTER install.sql:   mysql -u root -p < 08_app_user.sql
-- 1. Change the password below.  2. Use it in backend/.env:
--      DATABASE_URL=mysql+pymysql://cloudsched_app:YOUR_PASSWORD@127.0.0.1:3306/cloudsched
-- The procedures/triggers run with their definer's rights, so the app needs no DDL privileges.
-- (Use '%' instead of 'localhost' only if the API connects from another host / container.)
-- =====================================================================================
CREATE USER IF NOT EXISTS 'cloudsched_app'@'localhost' IDENTIFIED BY 'CHANGE_ME_STRONG_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE, CREATE TEMPORARY TABLES ON cloudsched.* TO 'cloudsched_app'@'localhost';
FLUSH PRIVILEGES;
