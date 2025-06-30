def calculate_sample_sizes(jurisdiction_counts: dict[str, int]) -> dict[str, int]:
    """
    Calculate stratified sample sizes by state using statistical formulas.

    Args:
        jurisdiction_counts (dict[str, int]): Dictionary mapping state names to counts of where we have citation data available.

    Returns:
        dict[str, int]: Dictionary mapping state names to sample sizes.
    """
    total_jurisdictions = sum(jurisdiction_counts.values())
    target_sample_size = 385  # From args.sample_size in main()
    
    # Calculate proportional allocation
    sample_strategy = {}
    allocated_total = 0

    for state, count in jurisdiction_counts.items():
        # Proportional allocation: (state_count / total_count) * target_sample
        proportion = count / total_jurisdictions
        sample_size = round(proportion * target_sample_size)
        
        # Ensure at least 1 sample per state if they have jurisdictions
        sample_size = max(1, min(sample_size, count))
        
        sample_strategy[state] = sample_size
        allocated_total += sample_size
    
    # Adjust for rounding errors to hit exact target
    difference = target_sample_size - allocated_total
    
    if difference != 0:
        # Sort states by jurisdiction count (descending) for adjustment
        states_by_size = sorted(jurisdiction_counts.items(), key=lambda x: x[1], reverse=True)
        
        # Add or subtract from largest states first
        for state, _ in states_by_size:
            if difference == 0:
                break
            
            if difference > 0 and sample_strategy[state] < jurisdiction_counts[state]:
                sample_strategy[state] += 1
                difference -= 1
            elif difference < 0 and sample_strategy[state] > 1:
                sample_strategy[state] -= 1
                difference += 1
    
    return sample_strategy
