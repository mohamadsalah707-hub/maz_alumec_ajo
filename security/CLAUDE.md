# Odoo Development Rules
- When asked to build or modify a feature, always test your changes before replying.
- To upgrade the DB and run tests, run this command in the terminal:
  `python3 odoo-bin -c odoo.conf -d demo19 -u maz_alumec_ajo --test-enable --test-tags=maz_alumec_ajo --stop-after-init`
- Ensure the terminal exit code is 0 and no tracebacks are present before finishing.