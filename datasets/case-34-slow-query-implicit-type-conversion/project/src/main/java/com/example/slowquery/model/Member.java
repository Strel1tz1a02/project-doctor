package com.example.slowquery.model;

import lombok.Data;

@Data
public class Member {
    private Long id;
    private String memberNo;
    private String nickname;
    private String level;
    private Long createdAtMs;
}
