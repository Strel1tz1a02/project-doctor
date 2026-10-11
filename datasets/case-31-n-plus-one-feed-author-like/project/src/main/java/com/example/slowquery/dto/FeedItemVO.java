package com.example.slowquery.dto;

import lombok.Data;

@Data
public class FeedItemVO {
    private long postId;
    private String content;
    private String authorNickname;
    private long likeCount;
}
