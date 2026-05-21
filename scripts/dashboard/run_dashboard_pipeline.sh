#!/bin/bash
# Dashboard Data Pipeline - Tổng hợp payload cho web dashboard
# Chạy enrichment và synthesis để tạo data cho dashboard

set -e

cd "$(dirname "$0")/../.."

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Default values
SKIP_ENRICH=false
SKIP_SYNTHESIS=false
DRY_RUN=false
CONTINUE_ON_ERROR=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --skip-enrich)
      SKIP_ENRICH=true
      shift
      ;;
    --skip-synthesis)
      SKIP_SYNTHESIS=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      export DRY_RUN=1
      shift
      ;;
    --continue-on-error)
      CONTINUE_ON_ERROR=true
      shift
      ;;
    -h|--help)
      echo -e "${BLUE}========================================${NC}"
      echo -e "${BLUE}   Dashboard Data Pipeline${NC}"
      echo -e "${BLUE}========================================${NC}"
      echo ""
      echo -e "${YELLOW}Usage:${NC}"
      echo "  ./scripts/dashboard/run_dashboard_pipeline.sh [options]"
      echo ""
      echo -e "${YELLOW}Options:${NC}"
      echo "  --skip-enrich         Skip OpenAI enrichment (mentions/reviews)"
      echo "  --skip-synthesis      Skip dashboard snapshot synthesis"
      echo "  --dry-run             Print what would be done without running"
      echo "  --continue-on-error   Continue even if a stage fails"
      echo "  -h, --help            Show this help message"
      echo ""
      echo -e "${YELLOW}Environment Variables:${NC}"
      echo "  OPENAI_API_KEY        Required for OpenAI enrichment"
      echo "  OPENAI_MODEL          Model to use (default: gpt-4o-mini)"
      echo "  PGDATABASE            PostgreSQL database (default: meili_dashboard)"
      echo "  PGSCHEMA              PostgreSQL schema (default: meili_dashboard)"
      echo "  BRAND_SLUG            Brand slug (default: meili-mi-bo-dai-loan)"
      echo ""
      echo -e "${YELLOW}Pipeline Stages:${NC}"
      echo "  1. Enrich mentions & reviews với OpenAI sentiment/topic analysis"
      echo "  2. Synthesize dashboard snapshot với OpenAI overview/insights"
      echo ""
      echo -e "${YELLOW}Examples:${NC}"
      echo "  ./scripts/dashboard/run_dashboard_pipeline.sh"
      echo "  ./scripts/dashboard/run_dashboard_pipeline.sh --dry-run"
      echo "  ./scripts/dashboard/run_dashboard_pipeline.sh --skip-enrich"
      echo ""
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Header
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Dashboard Data Pipeline${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check required environment variables
if [ "$DRY_RUN" = false ] && [ "$SKIP_ENRICH" = false ] && [ -z "$OPENAI_API_KEY" ]; then
  echo -e "${RED}Error: OPENAI_API_KEY is required${NC}"
  echo "Export it in your shell: export OPENAI_API_KEY=sk-..."
  exit 1
fi

# Display configuration
echo -e "${YELLOW}Configuration:${NC}"
echo "  PGDATABASE:    ${PGDATABASE:-meili_dashboard}"
echo "  PGSCHEMA:      ${PGSCHEMA:-meili_dashboard}"
echo "  BRAND_SLUG:    ${BRAND_SLUG:-meili-mi-bo-dai-loan}"
echo "  OPENAI_MODEL:  ${OPENAI_MODEL:-gpt-4o-mini}"
echo "  DRY_RUN:       ${DRY_RUN}"
echo ""

# Track overall status
OVERALL_STATUS=0

# Stage 1: Enrich mentions and reviews with OpenAI
if [ "$SKIP_ENRICH" = false ]; then
  echo -e "${BLUE}========================================${NC}"
  echo -e "${BLUE}Stage 1: OpenAI Enrichment${NC}"
  echo -e "${BLUE}========================================${NC}"
  echo ""
  echo -e "${GREEN}Enriching mentions & reviews với sentiment/topic analysis...${NC}"

  if [ "$DRY_RUN" = false ]; then
    if node scripts/dashboard/enrich_meili_postgres_openai.mjs; then
      echo -e "${GREEN}✓ Enrichment completed successfully${NC}"
    else
      echo -e "${RED}✗ Enrichment failed${NC}"
      OVERALL_STATUS=1
      if [ "$CONTINUE_ON_ERROR" = false ]; then
        exit 1
      fi
    fi
  else
    echo -e "${YELLOW}[DRY RUN] Would run: node scripts/dashboard/enrich_meili_postgres_openai.mjs${NC}"
  fi
  echo ""
else
  echo -e "${YELLOW}Skipping enrichment stage${NC}"
  echo ""
fi

# Stage 2: Synthesize dashboard snapshot with OpenAI
if [ "$SKIP_SYNTHESIS" = false ]; then
  echo -e "${BLUE}========================================${NC}"
  echo -e "${BLUE}Stage 2: Dashboard Synthesis${NC}"
  echo -e "${BLUE}========================================${NC}"
  echo ""
  echo -e "${GREEN}Synthesizing dashboard snapshot với OpenAI insights...${NC}"

  if [ "$DRY_RUN" = false ]; then
    if node scripts/dashboard/synthesize_dashboard_snapshot_openai.mjs; then
      echo -e "${GREEN}✓ Synthesis completed successfully${NC}"
    else
      echo -e "${RED}✗ Synthesis failed${NC}"
      OVERALL_STATUS=1
      if [ "$CONTINUE_ON_ERROR" = false ]; then
        exit 1
      fi
    fi
  else
    echo -e "${YELLOW}[DRY RUN] Would run: node scripts/dashboard/synthesize_dashboard_snapshot_openai.mjs${NC}"
  fi
  echo ""
else
  echo -e "${YELLOW}Skipping synthesis stage${NC}"
  echo ""
fi

# Summary
echo -e "${BLUE}========================================${NC}"
if [ $OVERALL_STATUS -eq 0 ]; then
  echo -e "${GREEN}   Pipeline completed successfully! 🎉${NC}"
  echo -e "${BLUE}========================================${NC}"
  echo ""
  echo -e "${GREEN}Dashboard payload is ready!${NC}"
  echo "Start dashboard server:"
  echo "  python3 -m social_listening.dashboard.server"
else
  echo -e "${YELLOW}   Pipeline completed with errors${NC}"
  echo -e "${BLUE}========================================${NC}"
fi

exit $OVERALL_STATUS
