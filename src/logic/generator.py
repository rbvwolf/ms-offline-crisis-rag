from foundry_local_sdk import FoundryLocalManager
from foundry_local_sdk.configuration import Configuration
from langchain_huggingface import HuggingFaceEmbeddings
# Import retrieve_content() from retriever.py
from retriever import retrieve_content

def setup_system():
    print("(*) Starting foundry local client")
    FoundryLocalManager.initialize(Configuration(app_name="OfflineCrisisRAG"))
    manager = FoundryLocalManager.instance
    
    # Hardware Acceleration GPU Setup
    print("(*) Analyzing system hardware for acceleration")
    available_eps = manager.discover_eps()
    
    priority_eps = ['CUDAExecutionProvider', 'DirectMLExecutionProvider', 'WebGpuExecutionProvider']
    
    selected_ep = None
    is_already_registered = False
    
    # Find the best available EP based on priority
    for target in priority_eps:
        for ep in available_eps:
            if getattr(ep, 'name', '') == target:
                selected_ep = target
                # Check if its already downloaded
                is_already_registered = getattr(ep, 'is_registered', False)
                break
        if selected_ep:
            break
    
    if selected_ep:
        print(f"(*) Compatible GPU provider found: {selected_ep}")
        if is_already_registered:
            print(f"[+] {selected_ep} is already registered. Skipping download.")
        else:
            print(f"(*) Downloading and registering {selected_ep}")
            try:
                manager.download_and_register_eps(names=[selected_ep])
                print(f"[+] Successfully registered {selected_ep}! Offloading tasks to GPU")
            except Exception as e:
                print(f"[-] Failed to register GPU provider. Falling back to CPU. Error: {e}")
    else:
        print("(*) No dedicated GPU provider found. Defaulting to CPU/RAM processing")
    #----------------------------------------------------------------------------
    
    model_name = "phi-3.5-mini"
    print(f"(*) Loading offline model: {model_name}")
    model = manager.catalog.get_model(model_name)
    try:
        model.load()
    except Exception:
        model.download()
        model.load()
        
    print("(*) Loading embedding model ONCE (Strictly Offline)...")
    embeddings_model = HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2",
        model_kwargs={'local_files_only': True}
    )
    
    return model, embeddings_model

def answer_query(user_question, model, embeddings_model):
    print(f"\n[?] Question: {user_question}")
    
    # 1. Retrieve the top context paragraphs from SQLite
    print("(*) Searching local database for answers")
    
    retrieved_docs = retrieve_content(user_question, embeddings_model, k=3)
    
    # Combine retrieved chunks into a single context string (filtering out bad distances)
    context_text = "\n\n".join([text for text, distance in retrieved_docs if distance <= 0.85])
    
    if not context_text:
        return "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının."
    
    # 2. Build the System Prompt using the context with XML and markdowns
    system_prompt = f"""You are the 'Offline Crisis Assistant', an AI designed to operate directly on a user's device during extreme emergencies where the internet is down. Your sole purpose is to save lives, provide calm psychological support, and manage resources safely.

    CRITICAL DIRECTIVES:
    1. STRICT GROUNDING (RAG): You must answer the user's query using ONLY the information provided in the <CONTEXT> block below. If the answer is not present in the context, you MUST state: "Veritabanımda bu bilgi bulunmuyor, lütfen varsayımlardan kaçının." Do NOT hallucinate or invent information under any circumstances.
    2. OUTPUT LANGUAGE: Use Turkish as default, if the user give input fully %100 English, use English. First language is TURKISH.
    3. CLI OPTIMIZATION: Your output will be displayed on a black terminal screen to save battery. Use extremely short, concise sentences. Use bullet points. Avoid long paragraphs.
    4. NO DISCLAIMERS: NEVER add explanations. NEVER add notes or disclaimers. Do NOT say "Not:" or "Note:". Just provide the raw facts.

    SPECIAL MODES & TRIGGERS:
    - PANIC & CHILD MODE: If the user input expresses fear, panic, or mentions crying children, instantly adopt a highly empathetic, calming, and soothing tone. Prioritize psychological first aid or fairy tales found in the <CONTEXT>.
    - TRIAGE MODE: For urgent medical situations, DO NOT provide a massive wall of text. Provide immediate first steps and ask a direct Yes/No question to guide the user (e.g., "Hastanın bilinci açık mı? (Evet/Hayır)").
    - RATION CALCULATION: If the user inputs numbers regarding food or water supplies, acknowledge the inventory and provide a strictly logical, daily rationing plan based on survival guidelines in the <CONTEXT>.

    <CONTEXT>
    {context_text}
    </CONTEXT>

    Remember: Keep it short, factual, in Turkish, and strictly bound to the context."""
    
    # 3. Send to local LLM
    print("(*) Generating answer from context")
    chat_client = model.get_chat_client()
    response = chat_client.complete_chat(
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_question}
        ]
    )
    
    return response.choices[0].message.content

if __name__ == "__main__":
    offline_model, embeddings_model = setup_system()
    print("\n" + "="*50)
    print("-- Çevrim Dışı Kriz Asistanı (Offline Crisis Assistant)--")
    print("Çıkmak için 'kapat', 'q', 'cikis', 'exit' yazın.")
    print("="*50)
    
    try:
        # Infinite CLI Loop
        while True:
            user_input = input("\n[Sen]: ")
            
            if user_input.lower() in ['kapat', 'q', 'cikis', 'exit']:
                print("(*) Sistem güvenlice kapatılıyor")
                break
            
            if not user_input.strip():
                continue
            
            final_answer = answer_query(user_input, offline_model, embeddings_model)
            
            print("\n" + "="*50)
            print("Asistan: ")
            print("="*50)
            print(final_answer)
        
    finally:
        offline_model.unload()