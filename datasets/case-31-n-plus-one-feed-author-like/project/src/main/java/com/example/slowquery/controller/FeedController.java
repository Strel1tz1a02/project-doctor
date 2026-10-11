package com.example.slowquery.controller;

import com.example.slowquery.dto.FeedItemVO;
import com.example.slowquery.service.FeedService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/feed")
public class FeedController {

    private final FeedService feedService;

    public FeedController(FeedService feedService) {
        this.feedService = feedService;
    }

    @GetMapping("/recent")
    public List<FeedItemVO> recent(@RequestParam(defaultValue = "100") int size) {
        return feedService.buildFeed(size);
    }
}
