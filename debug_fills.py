import sys
import os
import json

# Add parent dir to path to import okx_private
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from okx_private import OKXPrivateClient

def debug_fills():
    print("Debugging Account Fills...")
    
    # Try fetching without inst_id first
    print("\nAttempting to fetch ALL fills (last 3 days)...")
    result = OKXPrivateClient.get_fill_history(limit=20)
    print(f"Result Code: {result.get('code')}")
    if result.get('code') == '0':
        data = result.get('data', [])
        print(f"SUCCESS: Found {len(data)} fills.")
        for f in data:
            print(f"  • {f.get('fillTime')} | {f.get('instId')} | {f.get('side')} | {f.get('fillSz')} @ {f.get('fillPx')}")
    else:
        print(f"ERROR: {result.get('msg')}")
        print(f"Full Response: {json.dumps(result, indent=2)}")

    # Try fetching with instType=SPOT explicitly (if needed)
    # The current get_fill_history doesn't support instType, let's see if we need it.

if __name__ == "__main__":
    debug_fills()
