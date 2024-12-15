import requests
from solana.rpc.commitment import Confirmed
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.transaction import Transaction
from solders.pubkey import Pubkey
from solders.instruction import Instruction
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price

url = "https://api.mainnet-beta.solana.com"
headers = {"Content-Type": "application/json"}

def get_recent_prioritization_fees(addresses=None):
    """
    Fetch recent prioritization fees from the Solana JSON-RPC API.

    Args:
        url (str): The RPC endpoint URL.
        headers (dict): Headers to include in the POST request.
        addresses (list, optional): Specific addresses to query prioritization fees for.

    Returns:
        dict: The result containing prioritization fees.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getRecentPrioritizationFees",
        "params": [addresses] if addresses else []
    }

    try:
        response = requests.post(url=url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        response_data = response.json()

        if "result" not in response_data:
            raise ValueError("Invalid response: 'result' key not found.")
        
        return response_data['result']
    except requests.RequestException as e:
        print(f"Request failed: {e}")
        raise
    except ValueError as e:
        print(f"Invalid response format: {e}")
        raise

async def get_priority_fees(connection: AsyncClient) -> dict:
    """
    Get priority fees for the current block.

    Args:
        connection (AsyncClient): Solana RPC connection.

    Returns:
        dict: Priority fees statistics and instructions for different fee levels.
    """
    try:

        priority_fees_resp = get_recent_prioritization_fees()
        if not priority_fees_resp:
            return {"min": 0, "median": 0, "max": 0}

        sorted_fees = sorted(f["prioritizationFee"] for f in priority_fees_resp if "prioritizationFee" in f)

        if not sorted_fees:
            return {"min": 0, "median": 0, "max": 0}

        min_fee = sorted_fees[0]
        max_fee = sorted_fees[-1]
        mid = len(sorted_fees) // 2
        median_fee = (
            (sorted_fees[mid - 1] + sorted_fees[mid]) / 2 if len(sorted_fees) % 2 == 0 else sorted_fees[mid]
        )

        # Helper function to create instructions for priority fees
        def create_priority_fee_instruction(fee: int) -> Instruction:
            return set_compute_unit_price(micro_lamports=fee)

        return {
            "min": min_fee,
            "median": median_fee,
            "max": max_fee,
            "instructions": {
                "low": create_priority_fee_instruction(min_fee),
                "medium": create_priority_fee_instruction(median_fee),
                "high": create_priority_fee_instruction(max_fee),
            },
        }
    except Exception as e:
        print("Error getting priority fees:", e)
        raise

async def send_tx(agent, tx: Transaction, other_keypairs: list[Keypair] = None) -> str:
    """
    Send a transaction with priority fees.

    Args:
        agent: An object containing connection and wallet information.
        tx (Transaction): Transaction to send.
        other_keypairs (list[Keypair], optional): Additional signers. Defaults to None.

    Returns:
        str: Transaction ID.
    """
    try:
        # Fetch the latest blockhash
        latest_blockhash_resp = await agent.connection.get_latest_blockhash()
        latest_blockhash = latest_blockhash_resp["result"]["value"]["blockhash"]

        tx.recent_blockhash = latest_blockhash
        tx.fee_payer = Pubkey.from_string(agent.wallet_address)

        # Add the priority fee instruction
        fees = await get_priority_fees(agent.connection)
        if fees.get("instructions"):
            tx.add(fees["instructions"]["medium"])  # Add the medium fee level by default

        # Sign the transaction
        if other_keypairs:
            tx.sign(agent.wallet, *other_keypairs)
        else:
            tx.sign(agent.wallet)

        # Send the transaction
        tx_id = await agent.connection.send_raw_transaction(tx.serialize())
        await agent.connection.confirm_transaction(tx_id, commitment=Confirmed)
        return tx_id
    except Exception as e:
        print("Error sending transaction:", e)
        raise
