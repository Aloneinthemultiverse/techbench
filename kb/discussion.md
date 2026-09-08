# Discussion: Combining Shared Graph Reasoning with Fugu-style Orchestration

## Goal

Design a multi-agent AI system that combines:

-   **Fugu-style learned orchestration**
-   **A persistent shared reasoning graph**
-   **Multiple specialist LLMs**
-   **Verification and conflict resolution**

Instead of agents communicating only through prompts, every agent
collaborates through a shared graph that stores facts, evidence,
hypotheses, contradictions, confidence, and intermediate reasoning.

------------------------------------------------------------------------

# Motivation

Current approaches generally fall into two categories:

## 1. Orchestration-first systems

Examples: - Fugu - CrewAI - AutoGen

Characteristics: - Dynamic routing - Task decomposition - Prompt-based
communication - Little or no persistent structured reasoning

------------------------------------------------------------------------

## 2. Graph-first systems

Examples: - GraphRAG - Knowledge Graph QA

Characteristics: - Graph used for retrieval - Persistent memory -
Limited collaborative reasoning

------------------------------------------------------------------------

## Proposed Hybrid

    User
     │
     ▼
    RL Orchestrator
     │
     ├──────────────┬──────────────┬─────────────┐
     ▼              ▼              ▼
    Claude         GPT          Gemini
     │              │              │
     ├──── Read Shared Graph ──────┤
     ├──── Write New Nodes ────────┤
     ├──── Update Confidence ──────┤
     ├──── Detect Conflicts ───────┤
     └──────────────┬──────────────┘
                    ▼
             Verifier / Judge
                    │
                    ▼
              Final Response

------------------------------------------------------------------------

# Shared Graph Schema

## Node Types

-   Fact
-   Evidence
-   Hypothesis
-   Assumption
-   Question
-   Retrieval Chunk
-   Tool Output
-   Mathematical Result
-   Code Result
-   Verification
-   Contradiction

## Edge Types

-   supports
-   contradicts
-   derived_from
-   verified_by
-   generated_by
-   depends_on
-   refines
-   answers

------------------------------------------------------------------------

# Agent Workflow

1.  Read current graph.
2.  Retrieve missing evidence if necessary.
3.  Add structured reasoning.
4.  Link new nodes to existing knowledge.
5.  Detect conflicts.
6.  Update confidence.
7.  Pass graph to the next agent.

------------------------------------------------------------------------

# Verifier Responsibilities

Instead of comparing plain-text answers, the verifier evaluates the
graph:

-   Unsupported facts
-   Conflicting evidence
-   Circular reasoning
-   Missing citations
-   Low-confidence branches
-   Orphan hypotheses

------------------------------------------------------------------------

# RL Orchestrator

The orchestrator decides:

-   Which model to invoke
-   Which tool to use
-   Whether retrieval is needed
-   Whether verification is required
-   Whether another reasoning iteration is beneficial
-   When to stop

Possible reward signals:

-   Final answer correctness
-   Number of resolved contradictions
-   Evidence coverage
-   Graph consistency
-   Cost and latency
-   Hallucination rate

------------------------------------------------------------------------

# Potential Advantages

-   Persistent collaborative memory
-   Better explainability
-   Easier conflict resolution
-   Structured verification
-   Reusable intermediate reasoning
-   Improved multi-agent coordination

------------------------------------------------------------------------

# Research Questions

1.  Does a shared reasoning graph outperform prompt-only communication?
2.  Does graph-based verification reduce hallucinations?
3.  What graph representation works best?
4.  How should confidence propagate?
5.  Can orchestration policies learn graph-aware behaviors?

------------------------------------------------------------------------

# Experimental Baselines

Compare against:

-   Single frontier LLM
-   GraphRAG
-   AutoGen
-   CrewAI
-   Fugu-style orchestration (without shared graph)

Metrics:

-   Accuracy
-   Hallucination rate
-   Cost
-   Latency
-   Explainability
-   Graph consistency
-   User preference

------------------------------------------------------------------------

# Novelty

The proposed system does not simply combine orchestration and memory.

Its key idea is that the **shared graph becomes the primary
communication medium** among agents. Every model contributes structured
reasoning that subsequent agents can inspect, refine, verify, or
challenge. The orchestrator manages the workflow, while the graph
preserves the evolving reasoning state.

If effective, this would represent a hybrid of dynamic multi-agent
orchestration and persistent graph-based collaborative reasoning.
