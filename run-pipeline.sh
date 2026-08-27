#!/bin/bash
# Quick wrapper for running the full pipeline

set -e

cd "$(dirname "$0")"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Social Listening - Full Pipeline${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Show help if no arguments
if [ $# -eq 0 ]; then
    echo -e "${YELLOW}Usage:${NC}"
    echo "  ./run-pipeline.sh <platform> [options]"
    echo ""
    echo -e "${YELLOW}Platforms:${NC}"
    echo "  threads      - Threads platform"
    echo "  facebook     - Facebook platform"
    echo "  instagram    - Instagram platform"
    echo "  tiktok       - TikTok platform"
    echo "  youtube      - YouTube platform"
    echo "  google_maps  - Google Maps reviews"
    echo "  all          - All platforms"
    echo ""
    echo -e "${YELLOW}Options:${NC}"
    echo "  --skip-crawl         Skip crawl stage"
    echo "  --skip-format        Skip format job"
    echo "  --skip-filter        Skip keyword filter"
    echo "  --skip-sync          Skip PostgreSQL import"
    echo "  --only-crawl         Only run crawl stage"
    echo "  --continue-on-error  Continue even if a stage fails"
    echo "  --dry-run            Print commands without running"
    echo ""
    echo -e "${YELLOW}Examples:${NC}"
    echo "  ./run-pipeline.sh threads"
    echo "  ./run-pipeline.sh facebook --only-crawl"
    echo "  ./run-pipeline.sh all --skip-enrich"
    echo "  ./run-pipeline.sh instagram --dry-run"
    echo ""
    exit 0
fi

# Run the Python script
echo -e "${GREEN}Starting pipeline...${NC}"
echo ""

python3 scripts/marketing/run_full_pipeline.py "$@"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}   Pipeline completed successfully! 🎉${NC}"
    echo -e "${GREEN}========================================${NC}"
else
    echo ""
    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}   Pipeline failed with errors${NC}"
    echo -e "${YELLOW}========================================${NC}"
fi

exit $exit_code
