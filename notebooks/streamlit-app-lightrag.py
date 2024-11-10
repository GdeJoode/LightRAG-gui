import os
import sys
import requests
import asyncio
from contextlib import contextmanager
import logging
import PyPDF2
import xxhash
import networkx as nx
import time
import streamlit as st

# Set page config before any other Streamlit commands
st.set_page_config(
    page_title="LightRAG Demo on Streamlit",
    page_icon="😎",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        'Get help': "https://github.com/aiproductguy/LightRAG",
        'Report a bug': "https://github.com/HKUDS/LightRAG/issues",
        'About': """
        ##### LightRAG gui
        MIT open-source licensed GUI for LightRAG, a lightweight framework for retrieval-augmented generation:
        - [LightRAG Documentation](https://github.com/HKUDS/LightRAG)
        - [GUI Source Code](https://github.com/aiproductguy/LightRAG/notebooks/)
        - [Come to Demo Fridays at 12noon PT to say hi and give feedback!](https://cal.com/aiproductguy/lightrag-demo)
        - ©️ 2024 Bry at el #BothParentsMatter
        [![QRC|64](https://api.qrserver.com/v1/create-qr-code/?size=80x80&data=https://cal.com/aiproductguy/lightrag-demo)](https://cal.com/aiproductguy/lightrag-demo)
        """
    }
)

# Add the context manager right after imports
@contextmanager
def get_event_loop_context():
    """Context manager to handle asyncio event loop."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    yield loop

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

# Import LightRAG packages
from lightrag import LightRAG, QueryParam
from lightrag.llm import gpt_4o_mini_complete, openai_embedding
from lightrag.utils import EmbeddingFunc, logger, set_logger

# Configure logging
working_dir = "./dickens"
if not os.path.exists(working_dir):
    os.makedirs(working_dir)
    
set_logger(os.path.join(working_dir, "lightrag.log"))
logger.setLevel(logging.DEBUG)

# Rest of the imports
import streamlit as st

# Add constants after DEFAULT_LLM_MODEL
DEFAULT_LLM_MODEL = "gpt-4o-mini-2024-07-18"
DEFAULT_EMBEDDER_MODEL = "text-embedding-ada-002"

# Add model options constants
AVAILABLE_LLM_MODELS = [
    DEFAULT_LLM_MODEL,
    "gpt-4o-mini"  # Legacy model option
]

AVAILABLE_EMBEDDER_MODELS = [
    DEFAULT_EMBEDDER_MODEL,
    "text-embedding-3-small"  # New smaller model option
]

# Move helper functions and init_rag before the UI section
def get_llm_config(model_name):
    """Get the LLM configuration based on model name."""
    if model_name in [DEFAULT_LLM_MODEL, "gpt-4o-mini"]:
        return gpt_4o_mini_complete, model_name
    else:
        raise ValueError(f"Unsupported LLM model: {model_name}")

def get_embedding_config(model_name):
    """Get the embedding configuration based on model name."""
    embedding_configs = {
        "text-embedding-ada-002": {
            "dim": 1536,
            "max_tokens": 8192
        },
        "text-embedding-3-small": {
            "dim": 1536,
            "max_tokens": 8191
        }
    }
    
    if model_name not in embedding_configs:
        raise ValueError(f"Unsupported embedding model: {model_name}")
        
    config = embedding_configs[model_name]
    return EmbeddingFunc(
        embedding_dim=config["dim"],
        max_token_size=config["max_tokens"],
        func=lambda texts: openai_embedding(
            texts,
            model=model_name,
            api_key=st.session_state.settings["api_key"]
        )
    )

def test_api_key():
    """Test if OpenAI API key is valid and prompt for input if invalid."""
    if not st.session_state.settings["api_key"]:
        st.error("""
        ⚠️ OpenAI API key is required.
        Please enter your API key in the form below.
        """)
        show_api_key_form()
        return False
        
    try:
        from openai import OpenAI
        client = OpenAI(api_key=st.session_state.settings["api_key"])
        
        # Try a simple embedding request
        response = client.embeddings.create(
            input="test",
            model="text-embedding-ada-002"
        )

        # Send test prompt
        chat_response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "What is LightRAG?"}]
        )
        test_response = chat_response.choices[0].message.content

        # Log the test response
        add_activity_log(f"[T] Test prompt: What is LightRAG?\n[@] {test_response[:100]}...")
        
        return True
        
    except Exception as e:
        st.error(f"""
        ⚠️ API Error. Please ensure:
        1. You have entered a valid OpenAI API key
        2. Your API key has access to the text-embedding-ada-002 model
        
        Error details: {str(e)}
        """)
        
        show_api_key_form()
        return False

def show_api_key_form():
    """Display the API key input form."""
    with st.form("api_key_form"):
        new_api_key = st.text_input(
            "Enter your OpenAI API key:",
            type="password",
            help="Get your API key from https://platform.openai.com/account/api-keys"
        )
        
        submitted = st.form_submit_button("Save API Key")
        
        if submitted and new_api_key:
            st.session_state.settings["api_key"] = new_api_key
            st.session_state.initialized = False
            st.rerun()

def init_rag():
    """Initialize/reinitialize RAG."""
    if not test_api_key():  # Test API key before initializing
        return False
        
    working_dir = "./dickens"
    
    if not os.path.exists(working_dir):
        os.makedirs(working_dir)
    
    # Initialize RAG with current settings
    llm_func, llm_name = get_llm_config(st.session_state.settings["llm_model"])
    embedding_config = get_embedding_config(st.session_state.settings["embedding_model"])
        
    # Separate LLM kwargs from query settings
    llm_kwargs = {
        "temperature": st.session_state.settings["temperature"],
        "system_prompt": st.session_state.settings["system_prompt"],
        "api_key": st.session_state.settings["api_key"]
    }
    
    st.session_state.rag = LightRAG(
        working_dir=working_dir,
        llm_model_func=llm_func,
        llm_model_name=llm_name,
        llm_model_max_async=4,
        llm_model_max_token_size=32768,
        llm_model_kwargs=llm_kwargs,
        embedding_func=embedding_config
    )
    st.session_state.initialized = True

    # Log graph stats after initialization
    graph = st.session_state.rag.chunk_entity_relation_graph._graph
    if graph:
        nodes = graph.number_of_nodes()
        edges = graph.number_of_edges()
        add_activity_log(f"[*] Records: {nodes} nodes, {edges} edges")
    
    return True

# Move title to sidebar and add activity log first
st.sidebar.markdown("### [😎 LightRAG](https://github.com/HKUDS/LightRAG) [Kwaai](https://www.kwaai.ai/) Day [🔗](https://lightrag.streamlit.app)\n#alpha 2024-11-09")
st.sidebar.markdown("[![QRC|64](https://api.qrserver.com/v1/create-qr-code/?size=80x80&data=https://cal.com/aiproductguy/lightrag-demo)](https://cal.com/aiproductguy/lightrag-demo)")

# Add activity log section in sidebar
st.sidebar.markdown("##### Activity Log")

# Create a sidebar container for activity logs
activity_container = st.sidebar.container()

# Define all dialog functions first
@st.dialog("Insert Records")
def show_insert_dialog():
    """Dialog for inserting records from various sources."""
    tags = st.text_input(
        "Tags (optional):",
        help="Add comma-separated tags to help organize your documents"
    )
    
    tab1, tab2, tab3, tab4 = st.tabs(["Paste", "Upload", "Website", "Test"])
    
    with tab1:
        text_input = st.text_area(
            "Paste text or markdown content:",
            height=200,
            help="Paste your document content here"
        )
        
        if st.button("Insert", key="insert"):
            if text_input:
                handle_insert(text_input)
    
    with tab2:
        uploaded_file = st.file_uploader(
            "Choose a markdown file",
            type=['md', 'txt'],
            help="Upload a markdown (.md) or text (.txt) file"
        )
        
        if uploaded_file is not None:
            if st.button("Insert File", key="insert_file"):
                try:
                    content = uploaded_file.read()
                    if isinstance(content, bytes):
                        content = content.decode('utf-8')
                    handle_insert(content)
                except Exception as e:
                    st.error(f"Error inserting file: {str(e)}")
    
    with tab3:
        url = st.text_input(
            "Website URL:",
            help="Enter the URL of the webpage you want to insert"
        )
        
        if st.button("Insert", key="insert_url"):
            if url:
                try:
                    response = requests.get(url)
                    response.raise_for_status()
                    handle_insert(response.text)
                except Exception as e:
                    st.error(f"Error inserting website content: {str(e)}")
    
    with tab4:
        st.markdown("### Test Documents")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("Insert A Christmas Carol"):
                try:
                    with open("dickens/inbox/book.txt", "r", encoding="utf-8") as f:
                        content = f.read()
                        handle_insert(content)
                except Exception as e:
                    st.error(f"Error inserting Dickens test book: {str(e)}")
        
        with col2:
            if st.button("Insert LightRAG Paper"):
                try:
                    with open("dickens/inbox/2410.05779v2-LightRAG.pdf", "rb") as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        content = []
                        for page in pdf_reader.pages:
                            text = page.extract_text()
                            if text.strip():  # Only add non-empty pages
                                content.append(text)
                            
                        if not content:
                            st.error("No text could be extracted from the PDF")
                        else:
                            combined_content = "\n\n".join(content)
                            handle_insert(combined_content)
                except FileNotFoundError:
                    st.error("PDF file not found. Please ensure the file exists in dickens/inbox/")
                except Exception as e:
                    st.error(f"Error inserting LightRAG whitepaper: {str(e)}")

@st.dialog("Settings")
def show_settings_dialog():
    """Dialog for configuring LightRAG settings."""
    # Add API key input at the top
    api_key = st.text_input(
        "OpenAI API Key:",
        value=st.session_state.settings["api_key"],
        type="password",
        help="Enter your OpenAI API key"
    )
    if api_key != st.session_state.settings["api_key"]:
        st.session_state.settings["api_key"] = api_key
        st.session_state.initialized = False
    
    # Update model selection dropdowns with separate options
    st.session_state.settings["llm_model"] = st.selectbox(
        "LLM Model:",
        AVAILABLE_LLM_MODELS,
        index=AVAILABLE_LLM_MODELS.index(st.session_state.settings["llm_model"])
    )
    
    st.session_state.settings["embedding_model"] = st.selectbox(
        "Embedding Model:",
        AVAILABLE_EMBEDDER_MODELS,
        index=AVAILABLE_EMBEDDER_MODELS.index(st.session_state.settings["embedding_model"])
    )
    
    st.session_state.settings["search_mode"] = st.selectbox(
        "Search mode:",
        ["naive", "local", "global", "hybrid"],
        index=["naive", "local", "global", "hybrid"].index(st.session_state.settings["search_mode"])
    )
    
    st.session_state.settings["temperature"] = st.slider(
        "Temperature:",
        min_value=0.0,
        max_value=1.0,
        value=st.session_state.settings["temperature"],
        step=0.1
    )
    
    st.session_state.settings["system_prompt"] = st.text_area(
        "System Prompt:",
        value=st.session_state.settings["system_prompt"]
    )
    
    if st.button("Apply Settings"):
        handle_settings_update()
        st.rerun()

@st.dialog("Knowledge Graph Stats", width="large")
def show_kg_stats_dialog():
    """Dialog showing detailed knowledge graph statistics and visualization."""
    try:
        # Use the correct filename in dickens directory
        graph_path = "./dickens/graph_chunk_entity_relation.graphml"
        
        if not os.path.exists(graph_path):
            st.markdown("> [!graph] ⚠️ **Knowledge Graph file not found.** Please insert some documents first.")
            return
            
        graph = nx.read_graphml(graph_path)
            
        # Basic stats
        stats = {
            "Nodes": graph.number_of_nodes(),
            "Edges": graph.number_of_edges(),
            "Average Degree": round(sum(dict(graph.degree()).values()) / graph.number_of_nodes(), 2) if graph.number_of_nodes() > 0 else 0
        }
        
        # Display stats with more detail
        st.markdown("## Knowledge Graph Statistics")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Nodes", stats["Nodes"])
        with col2:
            st.metric("Total Edges", stats["Edges"])
        with col3:
            st.metric("Average Degree", stats["Average Degree"])
        
        # Add detailed analysis
        st.markdown("## Graph Analysis")
        
        # Calculate additional metrics
        if stats["Nodes"] > 0:
            density = nx.density(graph)
            components = nx.number_connected_components(graph.to_undirected())
            
            st.markdown(f"""
            - **Graph Density:** {density:.4f}
            - **Connected Components:** {components}
            - **Most Connected Nodes:**
            """)
                        
            # Create table headers
            table_lines = [
                "| Node ID | SHA-12 | Connections |",
                "|---------|--------|-------------|"
            ]
            
            # Add rows for top nodes
            degrees = dict(graph.degree())
            top_nodes = sorted(degrees.items(), key=lambda x: x[1], reverse=True)[:5]
            for node, degree in top_nodes:
                # Get first 12 chars of SHA hash
                sha_hash = xxhash.xxh64(node.encode()).hexdigest()[:12]
                table_lines.append(f"| `{node}` | `{sha_hash}` | {degree} |")
            
            # Display the table
            st.markdown("\n".join(table_lines))
        
        # Generate visualization if there are nodes
        if stats["Nodes"] > 0:
            st.markdown("## Knowledge Graph Visualization")
            
            try:
                from pyvis.network import Network
                import random
                
                st.markdown("*Generating interactive network visualization...*")
                
                net = Network(height="600px", width="100%", notebook=True)
                net.from_nx(graph)
                
                # Apply visual styling
                for node in net.nodes:
                    node["color"] = "#{:06x}".format(random.randint(0, 0xFFFFFF))
                
                # Save and display using the same filename pattern
                html_path = "./dickens/graph_chunk_entity_relation.html"
                net.save_graph(html_path)
                
                # Display the saved HTML
                with open(html_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                st.components.v1.html(html_content, height=600)
                    
            except ImportError:
                st.markdown("⚠️ Please install pyvis to enable graph visualization: `pip install pyvis`")
            except Exception as e:
                st.markdown(f"❌ **Error generating visualization:** {str(e)}")
        
    except Exception as e:
        logger.error(f"Error getting graph stats: {str(e)}")
        st.markdown(f"❌ **Error getting graph stats:** {str(e)}")

# Move this function before the dialog definitions
def handle_chat_download():
    """Download chat history as markdown."""
    if not st.session_state.messages:
        st.error("No messages to download yet! Start a conversation first.", icon="ℹ️")
        return
        
    from time import strftime
    
    # Create markdown content
    md_lines = [
        "# LightRAG Chat Session\n",
        f"*Exported on {strftime('%Y-%m-%d %H:%M:%S')}*\n",
        "\n## Settings\n",
        f"- Search Mode: {st.session_state.settings['search_mode']}",
        f"- LLM Model: {st.session_state.settings['llm_model']}",
        f"- Embedding Model: {st.session_state.settings['embedding_model']}",
        f"- Temperature: {st.session_state.settings['temperature']}",
        f"- System Prompt: {st.session_state.settings['system_prompt']}\n",
        "\n## Conversation\n"
    ]
    
    # Add messages
    for msg in st.session_state.messages:
        role = "User" if msg["role"] == "user" else "Assistant"
        md_lines.append(f"\n### {role} ({msg['metadata'].get('timestamp', 'N/A')})")
        md_lines.append(f"\n{msg['content']}\n")
        
        if msg["role"] == "assistant" and "metadata" in msg:
            metadata = msg["metadata"]
            if "query_info" in metadata:
                md_lines.append(f"\n> {metadata['query_info']}")
            if "error" in metadata:
                md_lines.append(f"\n> ⚠️ Error: {metadata['error']}")
    
    md_content = "\n".join(md_lines)
    
    st.download_button(
        label="Download Chat",
        data=md_content,
        file_name=f"chat_session_{strftime('%Y%m%d_%H%M%S')}.md",
        mime="text/markdown",
        key="download_chat"
    )

def get_all_records_from_graph():
    """Extract records from the knowledge graph."""
    try:
        graph_path = "./dickens/graph_chunk_entity_relation.graphml"
        if not os.path.exists(graph_path):
            return []
            
        graph = nx.read_graphml(graph_path)
        
        records = []
        for node in graph.nodes(data=True):
            node_id, data = node
            if data.get('type') == 'chunk':
                record = {
                    'id': node_id,
                    'content': data.get('content', ''),
                    'metadata': {
                        'type': data.get('type', ''),
                        'timestamp': data.get('timestamp', ''),
                        'relationships': []
                    }
                }
                
                # Get relationships
                for edge in graph.edges(node_id, data=True):
                    source, target, edge_data = edge
                    if edge_data:
                        record['metadata']['relationships'].append({
                            'target': target,
                            'type': edge_data.get('type', ''),
                            'weight': edge_data.get('weight', 1.0)
                        })
                
                records.append(record)
        
        return records
        
    except Exception as e:
        logger.error(f"Error reading graph file: {str(e)}")
        return []

@st.dialog("Download Options")
def show_download_dialog():
    """Dialog for downloading chat history and records."""
    st.markdown("### Download Options")
    
    tab1, tab2 = st.tabs(["Chat History", "Inserted Records"])
    
    with tab1:
        st.markdown("Download the current chat session as a markdown file.")
        handle_chat_download()
    
    with tab2:
        st.markdown("Download all inserted records as a JSON file.")
        if st.button("Download Records"):
            try:
                if st.session_state.rag is None:
                    st.error("No records available. Initialize RAG first.")
                    return
                    
                # Get records from graph
                records = get_all_records_from_graph()
                
                if not records:
                    st.warning("No records found to download.")
                    return
                
                import json
                from time import strftime
                
                # Convert records to JSON
                records_json = json.dumps(records, indent=2)
                
                # Create download button
                st.download_button(
                    label="Download JSON",
                    data=records_json,
                    file_name=f"lightrag_records_{strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json"
                )
                
                # Log success
                add_activity_log(f"[↓] Downloaded {len(records)} records")
                
            except Exception as e:
                logger.error(f"Error downloading records: {str(e)}")
                st.error(f"Error downloading records: {str(e)}")
                add_activity_log(f"[!] Download error: {str(e)}")

# Now add the buttons after all dialogs are defined
col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("➕", help="Insert Records"):
        show_insert_dialog()

with col2:
    if st.button("⚙", help="Settings"):
        show_settings_dialog()

with col3:
    if st.button("፨", help="Knowledge Graph Stats"):
        show_kg_stats_dialog()

with col4:
    if st.button("⬇", help="Download Options"):
        show_download_dialog()

# Create a container for chat history and AI output with border
chat_container = st.container(border=True)

# Add after the model constants but before session state initialization
def add_activity_log(message: str):
    """Add an entry to the activity log and display in sidebar."""
    # Initialize activity log if not exists
    if "activity_log" not in st.session_state:
        st.session_state.activity_log = []
        
    # Add new message
    st.session_state.activity_log.append(message)
    
    # Keep only last 50 entries to prevent too much history
    st.session_state.activity_log = st.session_state.activity_log[-50:]
    
    # Update sidebar display
    with activity_container:
        st.markdown(f"```\n{message}\n```")

# Initialize session state with API key
if "initialized" not in st.session_state:
    st.session_state.initialized = False
    st.session_state.settings = {
        "search_mode": "hybrid",
        "llm_model": DEFAULT_LLM_MODEL,
        "embedding_model": DEFAULT_EMBEDDER_MODEL,
        "system_prompt": "You are a helpful AI assistant that answers questions based on the provided records in Obsidian markdown format with use of #wikitags and [[wikilinks]].",
        "temperature": 0.7,
        "api_key": os.getenv("OPENAI_API_KEY", "")
    }
    st.session_state.rag = None
    st.session_state.messages = []
    st.session_state.activity_log = []
    
    # Add notice about API key source
    if st.session_state.settings["api_key"]:
        add_activity_log("ℹ️ Using OpenAI API key from environment")

# After initializing RAG, display initial stats
with chat_container: 
    if not st.session_state.initialized:
        init_rag()

# Define helper functions first
def handle_settings_update():
    """Update settings and force RAG reinitialization."""
    st.session_state.initialized = False  # Force reinitialization

# Add a visual separator for action footer
if prompt := st.chat_input("Ask away. Expect 60+ seconds processing. Patience in precision. "):
    # Input and controls in a row
    col1 = st.columns([1])[0]  # Simplified to just show the prompt
    with col1:
        st.write(prompt)

# Handle chat input
if prompt:
    add_activity_log(f"[?] Q: {prompt[:50]}..." if len(prompt) > 50 else f"[?] Q: {prompt}")
    
    # Generate response
    with st.chat_message("assistant"):
        status_placeholder = st.empty()
        
        with status_placeholder.status("Searching and generating response..."):
            query_param = QueryParam(mode=st.session_state.settings["search_mode"])
            try:
                with get_event_loop_context() as loop:
                    response = loop.run_until_complete(st.session_state.rag.aquery(prompt, param=query_param))
                
                # Create query info string
                prompt_hash = xxhash.xxh64(prompt.encode()).hexdigest()[:8]
                query_info = f"{st.session_state.settings['search_mode']}@{st.session_state.settings['llm_model']} #{prompt_hash}"
                
                # Replace status with expander
                with status_placeholder.expander(query_info, expanded=False):
                    st.write("**Query Details:**")
                    st.write(f"- Search Mode: {st.session_state.settings['search_mode']}")
                    st.write(f"- LLM Model: {st.session_state.settings['llm_model']}")
                    st.write(f"- Embedding Model: {st.session_state.settings['embedding_model']}")
                    st.write(f"- Temperature: {st.session_state.settings['temperature']}")
                    st.write(f"- Prompt Hash: {prompt_hash}")
                
                # Add response with metadata
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response,
                    "metadata": {
                        "timestamp": time.strftime('%H:%M:%S'),  # Use time.strftime instead of datetime
                        "search_mode": st.session_state.settings["search_mode"],
                        "llm_model": st.session_state.settings["llm_model"],
                        "embedding_model": st.session_state.settings["embedding_model"],
                        "temperature": st.session_state.settings["temperature"],
                        "prompt_hash": prompt_hash,
                        "query_info": query_info
                    }
                })
                
                st.write(response)
                
                # Log the response in activity log (moved inside try block)
                add_activity_log(f"[@] A: {response[:50]}..." if len(response) > 50 else f"[@] A: {response}")
                
            except Exception as e:
                error_msg = f"Error generating response: {str(e)}"
                logger.error(error_msg)
                add_activity_log(f"[!] {error_msg}")
                fallback_response = "I apologize, but I encountered an error while processing your request."
                
                # Add error response to messages
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": fallback_response,
                    "metadata": {
                        "search_mode": st.session_state.settings["search_mode"],
                        "llm_model": st.session_state.settings["llm_model"],
                        "embedding_model": st.session_state.settings["embedding_model"],
                        "error": str(e)
                    }
                })
                
                st.write(fallback_response)
                
                # Log the error in activity log
                add_activity_log(f"[!] {error_msg}")

# Modify handle_insert to use add_activity_log
def handle_insert(content):
    """Handle document insertion."""
    if st.session_state.rag is not None:
        try:
            # First verify API key is working
            if not test_api_key():
                return
                
            with st.spinner("Inserting content..."):
                # Log the content size for debugging
                add_activity_log(f"[*] Processing content ({len(content)} chars)...")
                
                with get_event_loop_context() as loop:
                    success = loop.run_until_complete(st.session_state.rag.ainsert(content))
                    
                    if success:
                        st.success("Content inserted successfully!")
                        add_activity_log(f"[+] Added content ({len(content)} chars)")
                    else:
                        st.error("Failed to insert content - no relationships extracted")
                        add_activity_log("[-] Failed to extract relationships from content")
                        
        except Exception as e:
            logger.exception("An error occurred during insertion.")
            st.error(f"An error occurred: {e}")
            add_activity_log(f"[!] Insert error: {str(e)}")
