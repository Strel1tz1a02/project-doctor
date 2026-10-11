package com.example.slowquery.controller;

import com.example.slowquery.model.Article;
import com.example.slowquery.service.ArticleService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/articles")
public class ArticleController {

    private final ArticleService articleService;

    public ArticleController(ArticleService articleService) {
        this.articleService = articleService;
    }

    @GetMapping("/search")
    public List<Article> search(@RequestParam(defaultValue = "spring") String keyword,
                                @RequestParam(defaultValue = "20") int limit) {
        return articleService.search(keyword, limit);
    }
}
