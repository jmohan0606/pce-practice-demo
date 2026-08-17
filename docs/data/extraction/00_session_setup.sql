-- 00_session_setup.sql — run at the START of EVERY database session,
-- BEFORE any extract. A temp table does not survive a reconnect, and a
-- token refresh IS a reconnect: after any re-auth, run this again.
-- (psql alternative for cohort_adv: \copy cohort_adv FROM 'data/real_test/cohort.txt')
SET statement_timeout = '600s';

CREATE TEMP TABLE cohort_adv (advisor_sid varchar(11) PRIMARY KEY);

INSERT INTO cohort_adv (advisor_sid) VALUES ('T000001'),('T000002'),('T000003'),('T000005'),('T000004'),('T000018'),('T000019'),('T000020'),('T000006'),('T000007'),('T000008'),('T000009'),('T000010'),('T000011'),('T000012'),('T000013'),('T000014'),('T000015'),('T000016'),('T000017');

CREATE TEMP TABLE scoped_acct AS
SELECT DISTINCT ltrim(trim(d.account_no),'0') AS k
FROM   pcr.fpic_daily_trade_details_tb_prod d
WHERE  d.trade_dt >= DATE '2026-04-01' AND d.trade_dt < DATE '2026-07-01'
  AND  d.advisor_sid IN (SELECT advisor_sid FROM cohort_adv);

CREATE INDEX ON scoped_acct (k);

ANALYZE scoped_acct;
