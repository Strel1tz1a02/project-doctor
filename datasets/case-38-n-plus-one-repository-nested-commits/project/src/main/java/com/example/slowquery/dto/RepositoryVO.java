package com.example.slowquery.dto;

import lombok.Data;

import java.util.List;

@Data
public class RepositoryVO {
    private long repositoryId;
    private String name;
    private List<CommitVO> commits;
}
