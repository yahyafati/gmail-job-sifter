# JobSift

JobSift is a lightweight email classification system that uses few-shot prompting with any LLM API compatible with the
OpenAI standard to categorize emails related to job activity.

## Features

* Classifies emails into:

    * Job Application
    * Job Rejection
    * Job Interview
    * Job Advertisement
    * None
* Few-shot LLM-based approach (no training required)
* Simple and extensible pipeline

## Approach

JobSift uses a structured system prompt with a small set of labeled examples to guide an LLM in performing
classification. This enables strong performance without building or training a dedicated model.

## Usage

1. Provide email text as input
2. Send request to an OpenAI-compatible LLM API with system + few-shot prompt
3. Receive a single label as output

## Requirements

* Python 3.x
* API key for an OpenAI-compatible LLM provider

## Notes

* Performance depends on prompt quality and examples
* Can be extended to batch processing or fine-tuning workflows

## Future Improvements

* Dataset creation for supervised training
* Hybrid models (embeddings + classifier)
* Confidence scoring and evaluation metrics
