def longest_common_subsequence_length(seq1: list [str], seq2: list [str]) -> int:
    """Calculate length of longest common subsequence between two sequences.
    # TODO Verify if this is the correct implementation of LCS.

    Args:
        seq1: First sequence
        seq2: Second sequence
        
    Returns:
        Length of longest common subsequence
    """
    # Dynamic programming implementation of LCS
    m, n = len(seq1), len(seq2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if seq1[i-1] == seq2[j-1]:
                dp[i][j] = dp[i-1][j-1] + 1
            else:
                dp[i][j] = max(dp[i-1][j], dp[i][j-1])
    
    return dp[m][n]