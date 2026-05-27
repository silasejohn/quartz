from enum import Enum


class Task(str, Enum):
    LOCAL_CSV_INGEST      = "local_csv_ingest"      # Local CSV -> player JSONs              <- implemented
    REMOTE_CSV_INGEST     = "remote_csv_ingest"     # Google Sheets -> player JSONs          <- stub
    OPGG_SCRAPE           = "opgg_scrape"           # OP.GG rank + champ in one session      <- implemented
    OPGG_SCRAPE_RANK      = "opgg_scrape_rank"      # OP.GG -> Account.rank_data             <- implemented
    LOG_SCRAPE_RANK       = "log_scrape_rank"       # LOG -> Account.rank_data (supplement)  <- stub
    OPGG_SCRAPE_CHAMP     = "opgg_scrape_champ"     # OP.GG -> Account.champion_data         <- implemented
    DPM_SCRAPE_CHAMP      = "dpm_scrape_champ"      # DPM.lol -> Account.champion_data       <- stub
    REWIND_SCRAPE_CHAMP   = "rewind_scrape_champ"   # Rewind.lol -> Account.champion_data    <- stub
    RIOT_ENRICH_PUUID     = "riot_enrich_puuid"      # Riot API -> Account.puuid              <- implemented
    AGGREGATE_RANK_STATS  = "aggregate_rank_stats"  # Account.rank_data -> PlayerStats       <- implemented
    AGGREGATE_CHAMP_POOL  = "aggregate_champ_pool"  # Account.champion_data -> PlayerStats   <- stub
    PV_COMPUTE            = "pv_compute"            # rank_data -> point values              <- implemented
    EXPORT                = "export"                # Player JSONs -> CSV slices             <- stub
