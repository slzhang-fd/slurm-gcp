#!/bin/bash
#
#SBATCH --job-name=hostname_sleep_sample
#SBATCH --output=out_%j.txt
#
#SBATCH -a 1-10
#SBATCH --nodes=2
R CMD BATCH --no-save --vanilla test.R $SLURM_ARRAY_TASK_ID.routput
