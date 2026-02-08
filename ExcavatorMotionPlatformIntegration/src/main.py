import asyncio
from CommunicationHub import CommunicationHub

async def main():
    try:
        hub = CommunicationHub()

        await hub.start_server()
        while True:
            await asyncio.sleep(3600)

    except KeyboardInterrupt:
        print("Keyboard interrupt -> shutting down the server...")
    finally:
        await hub.shutdown_server()
        
if __name__ == "__main__":
    asyncio.run(main())
