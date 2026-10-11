package com.example.slowquery.dto;

import lombok.Data;

@Data
public class CommitVO {
    private long commitId;
    private String message;
    private String committerName;
}
