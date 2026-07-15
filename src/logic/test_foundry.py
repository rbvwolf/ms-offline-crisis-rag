from foundry_local_sdk import FoundryLocalManager
from foundry_local_sdk.configuration import Configuration

def run_hello_model():
    print("(*) Foundry Local client starting")
    
    FoundryLocalManager.initialize(Configuration(app_name="OfflineCrisisRAG"))
    
    manager = FoundryLocalManager.instance
    
    # phi 1.5 mini doesnt work, so use phi-3.5-mini
    model_name = "phi-3.5-mini"
    print(f"(*) {model_name} loading... Download in first try.")
    
    # Take model to memory
    model = manager.catalog.get_model(model_name)
    
    try:
        print("(*) Model loading into memory")
        model.load()
        print("[+] Model is already downloaded, starting")
    
    except Exception:
        print("(*) Model couldnt found in the device, downloading...")
        model.download()
        model.load()
    
    chat_client = model.get_chat_client()
    response = chat_client.complete_chat(
        messages = [
            {"role": "user", "content": "Hello, world! Can you hear me?"}
        ]
    )
    
    print("\n" + "=" * 50)
    print("Model Response")
    print("=" * 50)
    
    if hasattr(response, 'choices'):
        print(response.choices[0].message.content)
    else:
        print(response)
        
    model.unload()
    
    print("\n[+] Test successful! Foundry Local SDK working without problems")
    
if __name__ == "__main__":
    run_hello_model()