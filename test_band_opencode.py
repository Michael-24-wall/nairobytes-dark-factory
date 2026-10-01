from band_sdk import BandClient
from band_sdk.adapters import OpencodeAdapter

client = BandClient.from_config("agent_config.yaml")

adapter = OpencodeAdapter(
    base_url="http://127.0.0.1:4096"
)

print("BAND configuration loaded.")
print("OpenCode adapter created.")
print("Ready to connect.")