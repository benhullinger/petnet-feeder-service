#!/bin/bash
cd /Users/ted/git/petnet-feeder-service

for pr in 437 436 435 433 432 430 429 428 427 426 424 420 415 413 412 411 410 409 408 407 406 405 399 398 396 394 387 376 374 373 372 371 370 351 336 322 321 314 312 307 303 297; do
  echo "Processing PR #$pr..."
  gh pr review $pr --approve --body "Approved by automated dependabot merge process" 2>&1 | head -5
  gh pr merge $pr --admin --squash --delete-branch 2>&1 | head -5
  echo "---"
done
