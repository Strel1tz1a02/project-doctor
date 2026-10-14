package com.example.slowquery.service;

import com.example.slowquery.dto.ArticleVO;
import com.example.slowquery.mapper.ArticleMapper;
import com.example.slowquery.model.Article;
import com.example.slowquery.model.Author;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class ArticleService {

    private final ArticleMapper articleMapper;

    public ArticleService(ArticleMapper articleMapper) {
        this.articleMapper = articleMapper;
    }

    public List<ArticleVO> recentArticlesWithAuthor(int size) {
        List<Article> articles = articleMapper.findRecentArticles(size);
        List<ArticleVO> result = new ArrayList<>();

        for (Article article : articles) {
            ArticleVO vo = new ArticleVO();
            vo.setArticleId(article.getId());
            vo.setTitle(article.getTitle());
            vo.setStatus(article.getStatus());
            vo.setCreatedAt(article.getCreatedAt());

            Author author = articleMapper.findAuthorById(article.getAuthorId());
            if (author != null) {
                vo.setAuthorName(author.getName());
                vo.setAuthorEmail(author.getEmail());
            }

            result.add(vo);
        }

        return result;
    }
}
