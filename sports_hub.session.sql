SELECT name, contract_salary, contract_total_value, contract_years, contract_expires 
FROM players 
WHERE team_id IN (1, 4) 
ORDER BY contract_total_value DESC NULLS LAST;