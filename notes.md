Think of a local AI setup as layers of capability stacked on top of a base model.

1. The Base Model (the "brain")

An LLM is the main neural network.

Examples:

Llama
Qwen
Mistral
Gemma

These models know language, coding, reasoning, etc.

Without anything else:

You -> LLM -> Answer
2. Quantization (making it fit)

Large models are huge.

Example:

Model	Full Size	Quantized
8B	~16 GB	4-6 GB
70B	~140 GB	40-50 GB

Common formats:

GGUF (CPU + GPU friendly)
EXL2 (GPU focused)
AWQ
GPTQ

Think:

Same brain, compressed.

A powerful home PC usually runs quantized models.

3. Inference Engine (the "car engine")

The model file is not enough.

You need software that runs it.

Examples:

llama.cpp
Ollama
vLLM
Text Generation WebUI

Flow:

Model
+
Inference Engine
=
Working AI
The "Helpers"

These are things added around or on top of the base model.

4. LoRA (small skill packs)

LoRA = Low-Rank Adaptation.

Think:

Base model
+
Skill addon
=
Specialized model

Examples:

Better coding
Better roleplay
Medical jargon
Writing style
Specific character

Instead of retraining 70 billion parameters:

70B model
+
200 MB LoRA

The LoRA only stores the differences.

Analogy

Base model:

Knows English.

LoRA:

Makes it speak like Shakespeare.

5. Fine-Tunes

A fine-tune is larger and more permanent.

Examples:

Base:

Llama

Fine-tunes:

Coding version
RP version
Assistant version

Think:

Original brain modified

Whereas LoRA is:

Original brain
+
Temporary attachment
6. RAG (external memory)

One of the most important concepts.

RAG = Retrieval Augmented Generation.

Instead of teaching the model everything:

Documents
↓
Search
↓
Relevant chunks
↓
LLM

Example:

You load:

PDFs
Notes
Obsidian vault
Source code

The model searches them before answering.

Analogy

Without RAG:

Answer from memory.

With RAG:

Open your notebook first.

Popular local tools:

Open WebUI
AnythingLLM
LibreChat
7. Embeddings (the librarian)

RAG requires embeddings.

Embeddings convert text into vectors.

Document
↓
Embedding model
↓
Numbers

The AI can then find semantically similar content.

Example:

Query:

How do I deploy Docker?

It can find:

Container deployment guide

Even if the words differ.

Think:

Search by meaning, not keywords.

8. Vector Database

Where embeddings live.

Examples:

Chroma
Qdrant
Milvus

Flow:

PDF
↓
Embedding
↓
Vector DB
↓
Search
↓
LLM
Agents
9. Agent

An agent is:

LLM
+
Tools
+
Ability to take actions

Example:

User:

Analyze this repo and write tests.

Agent:

Reads files
Searches code
Writes tests
Runs tests
Fixes failures

The LLM is acting, not just chatting.

Popular frameworks:

Open WebUI
LangChain
CrewAI
Image AI Helpers

Now the diffusion side.

10. Stable Diffusion / Flux (image brain)

Equivalent of an LLM but for images.

Examples:

Stable Diffusion
FLUX.1
Prompt
↓
Image Model
↓
Image
11. LoRA for Images

Exactly the same idea.

Add:

Art style
Character
Clothing
Face
Pose style
Flux
+
Anime LoRA
=
Anime specialist

Usually 100 MB–1 GB.

12. ControlNet (steering wheel)

ControlNet is one of the coolest helpers.

Instead of:

Prompt only

You provide structure.

Examples:

Pose Control

Input:

Stick figure

Output:

Generated person in same pose

Depth Control

Input:

Depth map

Output:

Keeps scene geometry

Line Art Control

Input:

Sketch

Output:

Finished artwork

Think:

LoRA changes knowledge.

ControlNet changes guidance.

13. IPAdapter (reference image helper)

Allows image generation based on another image.

Example:

Reference face
+
Prompt
=
Similar face

Useful for consistency.

14. Upscalers

Generate:

1024x1024

Then upscale:

4096x4096

Examples:

ESRGAN variants
RealESRGAN variants

Think:

AI enlargement.

15. Face Restoration

Examples:

GFPGAN
CodeFormer

Fixes:

Eyes
Skin
Facial artifacts

Common workflow:

Generate
↓
Upscale
↓
Restore face
What a Serious Home AI Setup Looks Like

For a powerful PC (e.g. 64GB+ RAM, RTX 4090/5090 class GPU):

Ollama
↓
Qwen or Llama
↓
Open WebUI
↓
RAG
↓
Your Documents

and

ComfyUI
↓
FLUX
↓
LoRAs
↓
ControlNets
↓
Upscalers

Key mental model:

LLM world
Base Model = Brain

LoRA = Skill Pack

RAG = Notebook

Embeddings = Librarian

Vector DB = Library

Agent = Employee with tools

Inference Engine = Engine
Image world
Base Model = Artist

LoRA = Style Pack

ControlNet = Steering Wheel

IPAdapter = Reference Image

Upscaler = Magnifying Glass

Face Restore = Retoucher

If you're building a local AI workstation in 2026, the most useful stack for a developer is usually:

Qwen 3 or Llama → Ollama → Open WebUI → RAG over your code/docs → coding agent tools, plus ComfyUI + FLUX + LoRAs + ControlNet for image generation. That's the setup that gives the biggest practical jump in capability beyond "just running a model."