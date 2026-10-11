package com.example.slowquery.model;

import lombok.Data;

@Data
public class Post {
    private long id;
    private long authorId;
    private String content;
    private long createdAtMs;
}
