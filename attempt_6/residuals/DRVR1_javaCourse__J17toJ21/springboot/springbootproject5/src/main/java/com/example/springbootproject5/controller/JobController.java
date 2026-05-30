package com.example.springbootproject5.controller;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import com.example.springbootproject5.model.Job;
import com.example.springbootproject5.service.JobService;

import java.util.List;

@RestController
public class JobController {

    @Autowired
    JobService jobService;

    @GetMapping("/jobs")
    public List<Job> getAllJobs() {
        return jobService.getAllJobs();
    }

    @GetMapping("/job/{id}")
    public Job getJobById(@PathVariable long id) {
        return jobService.getJobById(id);
    }

    @PostMapping("/job")
    public Job createJob(@RequestBody Job job) {
        return jobService.createJob(job);
    }

    @PutMapping("/job")
    public Job updateJob(@RequestBody Job job) {
        return jobService.updateJob(job);
    }

    @DeleteMapping("/job")
    public boolean deleteJob(@RequestBody Job job) {
        return jobService.deleteJob(job);
    }
}
