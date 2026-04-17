# Rise of Kingdoms - Network Analysis Report
**Date:** January 21, 2026

## Discovered Servers

### Primary Game Servers (Persistent Connections)
| IP | Port | Protocol | Provider | Purpose |
|---|---|---|---|---|
| 23.198.254.141 | 3101 | TCP/Custom | Akamai | **Main Game Server** (always connected) |
| 23.41.117.42 | 8080 | HTTP | Akamai | **Game API** (unencrypted!) |

### Secondary API Servers (HTTPS - Short-lived)
| IP | Port | Provider | Notes |
|---|---|---|---|
| 34.120.214.113 | 443 | Google Cloud | Backend API |
| 34.128.174.63 | 443 | Google Cloud | Backend API |
| 163.181.92.206 | 443 | Alibaba Cloud | CN Data |
| 163.181.92.208 | 443 | Alibaba Cloud | CN Data |
| 47.253.8.175 | 443 | Alibaba Cloud | CN Servers |
| 8.211.22.79 | 443 | Alibaba Cloud | CN Servers |

## Key Findings

### 1. Port 3101 - Main Game Protocol
- **Always connected** - this is the real-time game data
- Custom protocol (not HTTP)
- Likely binary/protobuf encoded
- This is where governor data flows

### 2. Port 8080 - HTTP API (Unencrypted!)
- **HTTP not HTTPS** - easier to intercept
- Akamai CDN endpoint
- Could be used for:
  - Asset downloads
  - Game state sync
  - Leaderboard data?

### 3. Infrastructure
- **Akamai** - CDN/Edge servers
- **Google Cloud** - API backend
- **Alibaba Cloud** - Chinese infrastructure (Lilith is Chinese)

## Next Steps

1. **Intercept port 8080** - Since it's HTTP, we can capture with mitmproxy
2. **Analyze port 3101 protocol** - Capture raw TCP data
3. **Try WireShark** - Capture full packet data for analysis

## Potential Attack Vectors for Data Extraction

1. **HTTP API (8080)** - Direct interception possible
2. **Memory reading** - Read game memory for governor data
3. **Protocol reverse engineering** - Decode the 3101 protocol

## Comparison with Competitors

Services like "Shining Warlord" (€34.99/month) claim instant KvK scanning.
They likely:
- Reverse engineered the protocol
- Have a bot that authenticates as a real player
- Query the game servers directly for data

This is **legally grey area** and possibly against ToS.
