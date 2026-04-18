graph TD
    %% Define Styles & Neon Glow
    classDef mainBox fill:#050a25,stroke:#fff,stroke-width:2px,color:#fff,rx:10,ry:10,font-weight:bold,glow:#fff;
    classDef agent fill:#050a25,stroke:#00d9ff,stroke-width:2px,color:#fff,rx:8,ry:8,font-weight:bold,glow:#00d9ff;
    classDef mcp fill:#050a25,stroke:#00ffb7,stroke-width:2px,color:#fff,rx:20,ry:20,font-weight:bold,glow:#00ffb7;
    classDef debate fill:#050a25,stroke:#ffae00,stroke-width:2px,color:#fff,rx:10,ry:10,font-weight:bold,glow:#ffae00;
    classDef verdict fill:#050a25,stroke:#00ff00,stroke-width:2px,color:#fff,rx:10,ry:10,font-weight:bold,glow:#00ff00;
    classDef feature fill:#050a25,stroke:#ff6f61,stroke-width:2px,color:#fff,rx:5,ry:5,font-weight:bold,glow:#ff6f61;

    %% Add Glow Filter to Entire Chart Area
    %% This uses HTML & CSS within the GitHub Markdown to add a glow.
    %% Unfortunately, it requires separate CSS block not always allowed.
    %% This can be faked with slightly fuzzy edges in static images or with advanced diagram tools.

    %% Define Main Title
    subgraph AFDE_Title [ ]
        direction TB
        Title["'AFDE' (Autonomous Financial Decision Engine)"]
    end
    Title -- Initial Input Request --> OrchNode

    %% Section 1: User Input to Orchestrator
    subgraph OrchGroup ["Orchestrator (LLM) - Analysis & Routing"]
        direction LR
        OrchNode("
            Orchestrator (LLM)
            - Parses Goal
            - Extracts Ticker
            - Routes Mode
        "):::agent
        
        OrchInputNode("User natural language goal"):::agent
    end

    %% Section 2: Orchestrator to 4 Agents (Parallel Split)
    subgraph AgentsGroup ["Autonomous LLM Agents"]
        direction TB
        FundAgent("Fundamental Agent (LLM)"):::agent
        InsAgent("Insider Agent (LLM)"):::agent
        MacroAgent("Macro Agent (LLM)"):::agent
        SentAgent("Sentiment Agent (LLM)"):::agent
    end

    %% Section 3: Agents to MCP Servers
    subgraph DataServers ["Data Access - MCP Servers"]
        direction LR
        FundServ("
            MCP Server:
            Yahoo Finance,
            SEC EDGAR
        "):::mcp
        InsServ("MCP Server: SEC Form 4"):::mcp
        MacroServ("MCP Server: FRED, VIX"):::mcp
        SentServ("MCP Server: Tavily News"):::mcp
    end

    %% Section 4: Agents to Agent Signal Objects
    SignalObjectsNode("Agent Signal Objects"):::feature

    %% Section 5: Debate Engine (Core Animation Highlight)
    subgraph DebateGroup ["Debate Engine"]
        direction TB
        DebateCenter{"Debate Engine"}:::debate
        BullNode("Bull"):::debate
        BearNode("Bear"):::debate
        JudgeNode("Judge"):::debate
        JudgeNode2("Judge"):::debate

        %% Central Loop Structure (Mermaid doesn't do true circles well)
        DebateCenter --> BullNode
        BullNode --> BearNode
        BearNode --> JudgeNode
        JudgeNode --> JudgeNode2
        JudgeNode2 --> BullNode
        
        %% Note: Mermaied can't easily draw true circular arrows
        %% The animation handles this visually.
    end

    %% Section 6: Debate to Macro Regime Adjustment
    MacroAdjNode("Macro Regime Adjustment"):::verdict

    %% Section 7: Final Verdict (Climax Animation)
    FinalVerdictNode("
        Final Verdict
        (BUY/HOLD/SELL)
        + Confidence
        + Audit Trail
    "):::verdict

    %% Section 8: Feature Outputs Animation
    subgraph FeatureGroup ["Feature Outputs"]
        direction LR
        SSEStreamNode("SSE Streaming"):::feature
        AgentMemoryNode("Agent Memory"):::feature
        PriceAlertsNode("Price Alerts"):::feature
        BacktestNode("Backtest Tracking"):::feature
        PDFExportNode("PDF Export"):::feature
        EmailNode("Email Notifications"):::feature
    end

    %% Section 9: APScheduler Timeline Animation
    subgraph SchedulerGroup ["APScheduler: Daily Jobs"]
        direction TB
        ShedHedaer("APScheduler Timeline")
        %% This requires specific timeline rendering, not basic flowchart.
        %% We describe the animation instead of complex timeline nodes.
    end

    %% Connect the Nodes and Define Data Flow Animations (Descriptions only)
    
    %% 1. User Input -> Orchestrator
    OrchInputNode --> |"*Flowing particle stream to simulate glowing data packet.*"| OrchNode

    %% 2. Orchestrator -> 4 Agents (Parallel Split)
    OrchNode --> |"*Parallel data streams with branching animation split.*"| FundAgent
    OrchNode --> |"*Parallel data streams with branching animation split.*"| InsAgent
    OrchNode --> |"*Parallel data streams with branching animation split.*"| MacroAgent
    OrchNode --> |"*Parallel data streams with branching animation split.*"| SentAgent

    %% 3. Agents -> MCP Servers
    FundAgent <--> |"*Downward request glow / Upward returning particles.*"| FundServ
    InsAgent <--> |"*Downward request glow / Upward returning particles.*"| InsServ
    MacroAgent <--> |"*Downward request glow / Upward returning particles.*"| MacroServ
    SentAgent <--> |"*Downward request glow / Upward returning particles.*"| SentServ

    %% 4. Agents -> Agent Signal Objects
    FundAgent --> |"*Colored signal pulses merging into node.*"| SignalObjectsNode
    InsAgent --> |"*Colored signal pulses merging into node.*"| SignalObjectsNode
    MacroAgent --> |"*Colored signal pulses merging into node.*"| SignalObjectsNode
    SentAgent --> |"*Colored signal pulses merging into node.*"| SignalObjectsNode

    %% 5. Debate Engine
    SignalObjectsNode --> DebateCenter
    %% Central circular loop has a 'rolling' animation described above.

    %% 6. Debate -> Macro Regime Adjustment
    JudgeNode2 --> |"*Single refined signal beam passes through glow filter.*"| MacroAdjNode

    %% 7. Final Verdict (Climax Animation)
    MacroAdjNode --> |"*Intense glow effect and bar filling up.*"| FinalVerdictNode

    %% 8. Feature Outputs Animation
    FinalVerdictNode --> |"*Multiple lines fan out to feature icons.*"| SSEStreamNode
    FinalVerdictNode --> |"*Multiple lines fan out to feature icons.*"| AgentMemoryNode
    FinalVerdictNode --> |"*Multiple lines fan out to feature icons.*"| PriceAlertsNode
    FinalVerdictNode --> |"*Multiple lines fan out to feature icons.*"| BacktestNode
    FinalVerdictNode --> |"*Multiple lines fan out to feature icons.*"| PDFExportNode
    FinalVerdictNode --> |"*Multiple lines fan out to feature icons.*"| EmailNode

    %% 9. APScheduler Timeline Animation
    Title -- Scheduled Job Kickoff --> ShedHedaer
    %% Internal timeline flow is purely described in animation notes.