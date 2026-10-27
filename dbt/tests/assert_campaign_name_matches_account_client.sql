{{ config(severity='warn') }}

-- A campaign named "BGE_..." running in Tidewater's ad account is either a naming
-- mistake or a campaign in the wrong account — both worth a human look.

select campaign_key, campaign_name, client_code, name_client_code
from {{ ref('dim_campaign') }}
where follows_naming_convention
  and name_client_code <> client_code
