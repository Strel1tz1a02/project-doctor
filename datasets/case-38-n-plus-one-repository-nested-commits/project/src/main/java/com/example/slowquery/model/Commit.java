package com.example.slowquery.model;

import lombok.Data;

@Data
public class Commit {
    private long id;
    private long repositoryId;
    private long committerId;
    private String message;
}
